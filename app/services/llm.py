"""
LLM 注册表与服务层 - 管理多个大语言模型的注册、切换和调用。

本模块包含两个核心类：
1. LLMRegistry: 模型注册表，定义所有可用的 LLM 及其配置。
2. LLMService: LLM 服务层，负责模型调用、重试、故障切换。

架构设计：
    - 支持 OpenAI 兼容协议的任何服务商（默认 DeepSeek 官方）。
    - 通过 OPENAI_BASE_URL 统一切换后端，无需修改代码。
    - 内置重试机制：遇到 RateLimitError/APITimeoutError/APIError 自动重试。
    - 故障切换：当前模型失败后自动切换到下一个可用模型（循环切换）。
    - 模型注册表支持运行时按名称获取、按索引获取。

使用示例：
    from app.services.llm import llm_service

    # 使用默认模型调用
    response = await llm_service.call(messages)

    # 指定模型调用
    response = await llm_service.call(messages, model_name="Qwen/Qwen3-VL-32B-Instruct")

    # 绑定工具后调用
    llm_service.bind_tools([my_tool])
    response = await llm_service.call(messages)
"""

from typing import (
    Any,
    Dict,
    List,
    Optional,
)

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
# 导入 OpenAI SDK 的各种错误类型（超时、限流、通用 API 错误）
from openai import (
    APIError,
    APITimeoutError,
    OpenAIError,
    RateLimitError,
)
# tenacity 是一个专门用于"自动重试"的库
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import (
    Environment,
    settings,
)
from app.core.logging import logger


# ============================================================================
# Langfuse 追踪回调
# ============================================================================
# 统一挂载 Langfuse CallbackHandler，使所有 LLM 调用自动产生 trace。
# 未配置密钥时返回 None（不追踪）。Langfuse v3 要求先初始化客户端再建
# CallbackHandler，否则回调无法关联到客户端（会静默跳过追踪）。
def _build_langfuse_handler() -> Optional[CallbackHandler]:
    if not (settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY):
        return None
    Langfuse(
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.LANGFUSE_SECRET_KEY,
        host=settings.LANGFUSE_HOST,
    )
    return CallbackHandler(public_key=settings.LANGFUSE_PUBLIC_KEY)


_LANGFUSE_HANDLER = _build_langfuse_handler()
_CALLBACKS = [_LANGFUSE_HANDLER] if _LANGFUSE_HANDLER else None


def get_langfuse_callbacks() -> Optional[List[CallbackHandler]]:
    """返回统一挂载的 Langfuse 回调列表（未配置密钥时为 None）。

    供 LangGraph 图调用层级使用：把回调挂到 ainvoke/astream 的 config["callbacks"]，
    这样图的「根 on_chain_start」会把 metadata 里的 langfuse_session_id/user_id/tags
    解析成 trace 级属性。否则这些 key 只落在 LLM 调用的 generation metadata 里，
    无法在 Langfuse 的 Sessions / Users 页面聚合。
    """
    return _CALLBACKS


def _chat_openai(model: str, **kwargs) -> ChatOpenAI:
    """构造 ChatOpenAI，并统一挂载 Langfuse 追踪回调。"""
    return ChatOpenAI(model=model, callbacks=_CALLBACKS, **kwargs)


class LLMRegistry:
    """
    大语言模型注册表 - 管理所有可用的聊天模型。

    设计目标：
    1. 集中管理：所有模型定义在一个地方，方便维护和审计。
    2. 即插即用：通过 ChatOpenAI 兼容 OpenAI 协议，切换服务商只需改 BASE_URL。
    3. 参数差异化：不同模型可以有不同的 temperature、max_tokens 等参数。

    当前注册的模型（DeepSeek 官方 API）：
    ┌──────────────────────┬──────────────────────────────────────┐
    │ 注册名                │ 说明                                  │
    ├──────────────────────┼──────────────────────────────────────┤
    │ deepseek-v4-pro      │ DeepSeek V4 Pro（默认模型）            │
    │ deepseek-chat        │ DeepSeek-V3 对话模型（备胎）            │
    │ deepseek-reasoner    │ DeepSeek-R1 推理模型（备胎，无温度）     │
    └──────────────────────┴──────────────────────────────────────┘

    注意：所有模型共享同一个 OPENAI_BASE_URL（DeepSeek 官方），
    切换服务商只需修改 config.py 中的 OPENAI_BASE_URL。
    原 SiliconFlow 模型（deepseek-ai/DeepSeek-V3.2 等）已移除，
    如需切回硅基流动请恢复相应条目并把 OPENAI_BASE_URL 改回
    https://api.siliconflow.cn/v1。
    """

    # 类级别的变量，存储所有可用的 LLM 模型
    # 每个元素是一个字典，包含模型名称和对应的 ChatOpenAI 实例
    LLMS: List[Dict[str, Any]] = [
        {
            "name": "deepseek-v4-pro",
            "llm": _chat_openai(
                "deepseek-v4-pro",
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_BASE_URL,  # DeepSeek 官方 API
                temperature=settings.DEFAULT_LLM_TEMPERATURE,  # 若报"不支持 temperature"可移除此行
                max_tokens=settings.MAX_TOKENS,
            ),
        },
        {
            "name": "deepseek-chat",
            "llm": _chat_openai(
                "deepseek-chat",
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_BASE_URL,  # DeepSeek 官方 API
                temperature=settings.DEFAULT_LLM_TEMPERATURE,
                max_tokens=settings.MAX_TOKENS,
            ),
        },
        {
            "name": "deepseek-reasoner",
            "llm": _chat_openai(
                "deepseek-reasoner",
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_BASE_URL,  # DeepSeek 官方 API
                # 注意：deepseek-reasoner（R1 推理模型）不支持 temperature 参数
                max_tokens=settings.MAX_TOKENS,
            ),
        },
    ]

    @classmethod
    def get(cls, model_name: str, **kwargs) -> BaseChatModel:
        """
        根据模型名称返回对应的 LLM 实例。

        如果提供了额外的关键字参数（如 temperature 覆盖），
        会创建一个新的 ChatOpenAI 实例（覆盖注册表中的默认参数），
        而不是返回注册表中的预构建实例。

        Args:
            model_name: 模型注册名（如 "deepseek-chat"）。
            **kwargs: 传递给 ChatOpenAI 的额外参数。

        Returns:
            BaseChatModel: 配置好的 LangChain 聊天模型实例。

        Raises:
            ValueError: 当模型名不在注册表中时抛出。
        """
        # 1. 在列表里找名字匹配的模型
        model_entry = None
        for entry in cls.LLMS:
            if entry["name"] == model_name:
                model_entry = entry
                break

        # 2. 如果没找到，按 OpenAI 兼容模型名动态创建
        if not model_entry:
            logger.info("creating_dynamic_llm_instance", model_name=model_name)
            return _chat_openai(
                model_name,
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_BASE_URL,
                temperature=settings.DEFAULT_LLM_TEMPERATURE,
                max_tokens=settings.MAX_TOKENS,
            )

        # 3. 如果传入了自定义参数（如 temperature、max_tokens 等），创建新的实例
        if kwargs:
            logger.debug("creating_llm_with_custom_args", model_name=model_name, custom_args=list(kwargs.keys()))
            return _chat_openai(model_name, api_key=settings.OPENAI_API_KEY, **kwargs)

        # 4. 否则直接返回预先准备好的那个
        logger.debug("using_default_llm_instance", model_name=model_name)
        return model_entry["llm"]

    @classmethod
    def get_all_names(cls) -> List[str]:
        """
        返回所有可用模型的名称列表。

        Returns:
            List[str]: 注册表中所有模型的名称。
        """
        # 列表推导式：遍历 LLMS 列表，只取出每个字典里的 "name" 字段
        return [entry["name"] for entry in cls.LLMS]

    @classmethod
    def get_model_at_index(cls, index: int) -> Dict[str, Any]:
        """
        根据索引获取模型条目（字典，包含 name 和 llm）。

        如果索引越界，则返回第一个（安全机制，防止崩溃）。

        Args:
            index: 模型在注册表列表中的索引。

        Returns:
            Dict[str, Any]: 模型条目字典（包含 name 和 llm 字段）。
        """
        # 检查索引是否越界（比如一共 5 个模型，不能取第 10 个）
        if 0 <= index < len(cls.LLMS):
            return cls.LLMS[index]
        # 越界时默认返回第一个（安全机制，防止程序崩溃）
        return cls.LLMS[0]


class LLMService:
    """
    LLM 服务层 - 管理模型的调用、重试和故障切换。

    核心功能：
    1. 自动选择模型：根据 DEFAULT_LLM_MODEL 配置初始化默认模型。
    2. 智能重试：使用 tenacity 库，对临时性错误（限流、超时、API 错误）自动重试。
       重试策略：指数退避（2s → 4s → 8s，最多重试 3 次）。
    3. 故障切换：当前模型失败后，自动切换到下一个可用模型（循环切换）。
       例如：deepseek-v4-pro 失败 → 自动切换到 deepseek-chat → deepseek-reasoner → ...
    4. 工具绑定：支持将 LangChain Tool 绑定到 LLM，使其能够调用外部工具。

    使用方式：
        from app.services.llm import llm_service
        response = await llm_service.call(messages)
    """

    def __init__(self):
        """
        初始化 LLM 服务 - 定位并实例化默认模型。

        如果配置的默认模型不存在，会回退到注册表中的第一个模型。
        """
        # 当前使用的 LLM 实例
        self._llm: Optional[BaseChatModel] = None
        # 当前模型在注册表中的索引（用于故障切换）
        self._current_model_index: int = 0

        # 1. 拿到所有模型的名字列表
        all_names = LLMRegistry.get_all_names()
        try:
            # 2. 尝试定位默认模型
            # .index() 方法会查找默认模型名在列表里的位置
            self._current_model_index = all_names.index(settings.DEFAULT_LLM_MODEL)
            # 3. 实例化默认模型
            self._llm = LLMRegistry.get(settings.DEFAULT_LLM_MODEL)
            # 记录成功日志
            logger.info(
                "llm_service_initialized",
                default_model=settings.DEFAULT_LLM_MODEL,
                model_index=self._current_model_index,
                total_models=len(all_names),
                environment=settings.ENVIRONMENT.value,
            )
        except (ValueError, Exception) as e:
            # === 异常处理 / 保底逻辑 ===
            # 如果默认模型名在列表里找不到（配置错误），回退到第一个模型
            self._current_model_index = 0
            self._llm = LLMRegistry.LLMS[0]["llm"]
            logger.warning(
                "default_model_not_found_using_first",
                requested=settings.DEFAULT_LLM_MODEL,
                using=all_names[0] if all_names else "none",
                error=str(e),
            )

    def _get_next_model_index(self) -> int:
        """
        计算下一个模型的索引（循环切换）。

        使用取模运算实现循环：
        - 假设总共 5 个模型 (索引 0~4)
        - 当前 0 → (0+1)%5 = 1
        - 当前 4 → (4+1)%5 = 0（回到开头，形成循环）

        Returns:
            int: 下一个模型的索引。
        """
        total_models = len(LLMRegistry.LLMS)
        next_index = (self._current_model_index + 1) % total_models
        return next_index

    def _switch_to_next_model(self) -> bool:
        """
        切换到下一个模型（故障切换）。

        Returns:
            bool: 切换是否成功。
        """
        try:
            # 1. 计算下一个模型的索引
            next_index = self._get_next_model_index()
            # 2. 获取下一个模型的条目
            next_model_entry = LLMRegistry.get_model_at_index(next_index)
            # 记录切换警告日志
            logger.warning(
                "switching_to_next_model",
                from_index=self._current_model_index,
                to_index=next_index,
                to_model=next_model_entry["name"],
            )
            # 3. 更新当前索引
            self._current_model_index = next_index
            # 4. 替换当前 LLM 实例
            self._llm = next_model_entry["llm"]

            logger.info("model_switched", new_model=next_model_entry["name"], new_index=next_index)
            return True
        except Exception as e:
            logger.error("model_switch_failed", error=str(e))
            return False

    # =========================================================================
    # tenacity 装饰器：为 _call_llm_with_retry 方法添加自动重试能力
    # 它的作用是：把下面这个函数包裹起来，给它穿上一层"复活甲"
    # =========================================================================
    @retry(
        stop=stop_after_attempt(settings.MAX_LLM_CALL_RETRIES),  # 最多重试 N 次（由配置决定，默认 3 次）
        wait=wait_exponential(multiplier=1, min=2, max=10),  # 指数退避等待：2s → 4s → 8s（最大 10s）
        # 只重试"可救"的错误：限流、超时、服务器内部错误
        # 并不是所有错误都重试，比如"认证失败"重试一万次也没用
        retry=retry_if_exception_type((RateLimitError, APITimeoutError, APIError)),
        # 每次等待重试前记录一条日志
        before_sleep=before_sleep_log(logger, "WARNING"),
        # 如果最终仍失败，重新抛出最后一次异常（不吞掉错误）
        reraise=True,
    )
    async def _call_llm_with_retry(self, messages: List[BaseMessage]) -> BaseMessage:
        """
        核心调用方法：使用当前模型异步调用 LLM，并带有重试机制。

        如果遇到可重试错误（限流/超时/API 错误），会由 @retry 装饰器自动重试；
        遇到不可重试错误（如认证失败）则直接抛出。

        Args:
            messages: 要发送给 LLM 的消息列表。

        Returns:
            BaseMessage: LLM 的回复消息。

        Raises:
            RuntimeError: LLM 未初始化时抛出。
            RateLimitError/APITimeoutError/APIError: 可重试错误，会触发重试。
            OpenAIError: 其他不可重试的 API 错误。
        """
        if not self._llm:
            raise RuntimeError("llm not initialized")

        try:
            # ainvoke 是 LangChain 的异步调用方法
            response = await self._llm.ainvoke(messages)
            # 成功则记录日志并返回结果
            logger.debug("llm_call_successful", message_count=len(messages))
            return response
        except (RateLimitError, APITimeoutError, APIError) as e:
            # 可重试的错误：记录警告后重新抛出，让 @retry 装饰器接住并安排重试
            logger.warning(
                "llm_call_failed_retrying",
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            raise  # 关键：把错误抛出去，让 @retry 感知并重试
        except OpenAIError as e:
            # 其他 OpenAI 错误（如认证错误、无效请求），不可重试，直接记录并抛出
            logger.error(
                "llm_call_failed",
                error_type=type(e).__name__,
                error=str(e),
            )
            raise

    async def call(
        self,
        messages: List[BaseMessage],
        model_name: Optional[str] = None,
        **model_kwargs,
    ) -> BaseMessage:
        """
        对外接口：调用 LLM，支持指定模型、自定义参数，并内置故障切换逻辑。

        调用流程：
        1. 如果指定了 model_name，临时切换到该模型（覆盖当前默认）。
        2. 循环尝试当前模型（最多尝试所有模型）：
           - 调用 _call_llm_with_retry（内部有重试）。
           - 成功则返回结果。
           - 失败则切换到下一个模型继续尝试。
        3. 如果所有模型都失败，抛出 RuntimeError。

        Args:
            messages: 要发送给 LLM 的消息列表。
            model_name: 可选，指定要使用的模型名称。
            **model_kwargs: 传递给模型的额外参数（如 temperature）。

        Returns:
            BaseMessage: LLM 的回复消息。

        Raises:
            ValueError: 指定的 model_name 不在注册表中。
            RuntimeError: 所有模型都调用失败。
        """
        # 如果用户指定了模型，从注册表获取
        if model_name:
            try:
                self._llm = LLMRegistry.get(model_name, **model_kwargs)
                # 更新当前索引以匹配请求的模型
                all_names = LLMRegistry.get_all_names()
                try:
                    self._current_model_index = all_names.index(model_name)
                except ValueError:
                    pass  # 如果模型名不在列表中（可能因自定义参数新建），保持当前索引不变
                logger.info("using_requested_model", model_name=model_name, has_custom_kwargs=bool(model_kwargs))
            except ValueError as e:
                logger.error("requested_model_not_found", model_name=model_name, error=str(e))
                raise

        # 记录已尝试的模型数量，防止无限循环
        total_models = len(LLMRegistry.LLMS)
        models_tried = 0
        starting_index = self._current_model_index  # 记住从哪个模型开始尝试
        last_error = None

        # 只要试过的模型数量还没超过总数，就一直循环
        while models_tried < total_models:
            try:
                response = await self._call_llm_with_retry(messages)
                return response  # 成功！直接返回，结束函数
            except OpenAIError as e:
                last_error = e
                models_tried += 1
                current_model_name = LLMRegistry.LLMS[self._current_model_index]["name"]
                logger.error(
                    "llm_call_failed_after_retries",
                    model=current_model_name,
                    models_tried=models_tried,
                    total_models=total_models,
                    error=str(e),
                )

                # 如果所有模型都试过了，跳出循环
                if models_tried >= total_models:
                    logger.error(
                        "all_models_failed",
                        models_tried=models_tried,
                        starting_model=LLMRegistry.LLMS[starting_index]["name"],
                    )
                    break

                # 切换到下一个模型继续尝试
                if not self._switch_to_next_model():
                    logger.error("failed_to_switch_to_next_model")
                    break

        # 如果循环结束还没返回，说明所有模型都失败了
        raise RuntimeError(
            f"failed to get response from llm after trying {models_tried} models. last error: {str(last_error)}"
        )

    def get_llm(self) -> Optional[BaseChatModel]:
        """
        获取当前使用的 LLM 实例。

        Returns:
            Optional[BaseChatModel]: 当前 LLM 实例（可能为 None，如果未初始化）。
        """
        return self._llm

    def bind_tools(self, tools: List) -> "LLMService":
        """
        给当前 LLM 绑定工具（如联网搜索、计算器等）。

        这是 LangChain 的标准操作：绑定后模型可以调用这些工具。
        bind_tools 会把工具定义注入到 LLM 的上下文中，
        使 LLM 在需要时生成 tool_calls 请求。

        Args:
            tools: LangChain Tool 对象列表。

        Returns:
            LLMService: 返回 self，支持链式调用（如 llm_service.bind_tools(tools).call(messages)）。
        """
        if self._llm:
            # 将工具绑定到模型上，绑定后模型就知道自己有哪些工具可用
            self._llm = self._llm.bind_tools(tools)
            logger.debug("tools_bound_to_llm", tool_count=len(tools))
        return self


# ============================================================================
# 全局单例实例
# ============================================================================
# 整个应用共享同一个 LLMService 实例
# 通过 `from app.services.llm import llm_service` 引用
llm_service = LLMService()
