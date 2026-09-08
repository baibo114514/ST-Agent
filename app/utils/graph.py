"""
图消息处理工具模块 - 负责消息的标准化、裁剪和转换为 LLM 可接收的格式。

本模块是 LangGraph Agent 与 LLM 之间的消息处理桥梁：

核心功能：
1. dump_messages: 将消息列表转为字典列表（用于日志记录和调试）。
2. prepare_messages: 准备消息列表（标准化 → 裁剪 → 注入 System Prompt）。
3. process_llm_response: 处理 LLM 响应，提取结构化内容。
4. get_token_count: 估算消息列表的 Token 数量。

修复说明：
1. 彻底重构 prepare_messages：不再使用 dict 中转，直接操作 LangChain BaseMessage 对象。
   确保 ToolMessage 和包含 tool_calls 的 AIMessage 能被正确传递给 LLM。
2. 修复工具调用上下文丢失的问题：确保 ToolMessage 和含 tool_calls 的 AIMessage 能正确传递。
3. 优化 get_token_count：增强对不同消息类型的兼容性。
"""

from typing import List, Union, Any

import tiktoken
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    BaseMessage,
    SystemMessage,
    HumanMessage,
    AIMessage,
    ToolMessage,  # 工具调用结果消息
    trim_messages as _trim_messages,  # LangChain 内置的消息裁剪函数
)

from app.core.config import settings
from app.core.logging import logger
from app.schemas import Message


def dump_messages(messages: List[Union[Message, BaseMessage, dict, Any]]) -> List[dict]:
    """
    辅助函数：将混合类型的消息列表统一转换为字典列表。

    主要用于日志记录和调试，不参与核心业务逻辑。

    支持的消息类型：
    - dict: 直接使用。
    - Pydantic v2 / LangChain 0.3+ (model_dump): 调用 model_dump()。
    - LangChain 旧版 / Pydantic v1 (dict): 调用 dict()。
    - 其他类型: 包装为 {"role": "user", "content": str(msg)}。

    Args:
        messages: 混合类型的消息列表。

    Returns:
        List[dict]: 统一格式的字典列表，可直接 JSON 序列化。
    """
    dumped = []
    for msg in messages:
        if isinstance(msg, dict):
            dumped.append(msg)
        elif hasattr(msg, "model_dump"):  # Pydantic v2 / LangChain 新版本
            dumped.append(msg.model_dump())
        elif hasattr(msg, "dict"):  # LangChain 旧版 / Pydantic v1
            dumped.append(msg.dict())
        else:
            dumped.append({"role": "user", "content": str(msg)})
    return dumped


def process_llm_response(response: BaseMessage) -> BaseMessage:
    """
    处理 LLM 响应，提取结构化内容。

    某些模型（如支持 reasoning 的模型）的响应 content 是一个列表，
    包含多种类型的块（text、reasoning 等）。此函数：
    1. 提取所有 text 类型的块，拼接为纯文本。
    2. 记录 reasoning 块的摘要到日志（用于调试）。
    3. 如果没有任何 text 块，将 content 设为空字符串。

    Args:
        response: LLM 返回的原始 BaseMessage 对象。

    Returns:
        BaseMessage: 处理后的消息对象（content 变为纯文本字符串）。
    """
    if isinstance(response.content, list):
        text_parts = []
        for block in response.content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    # 提取普通文本块
                    text_parts.append(block.get("text", ""))
                elif block.get("type") == "reasoning":
                    # 推理块（如 DeepSeek 的思维链），记录摘要但不展示给用户
                    logger.debug("llm_reasoning_block", content=block.get("summary"))

        # 拼接所有文本块
        if text_parts:
            response.content = "".join(text_parts)
        elif not isinstance(response.content, str):
            response.content = ""

    return response


def get_token_count(messages: List[Union[dict, BaseMessage]]) -> int:
    """
    自定义 Token 计数器 - 估算消息列表的 Token 数量。

    使用 tiktoken 的 cl100k_base 编码器（GPT-4 / DeepSeek 兼容）进行估算。
    如果 cl100k_base 不可用，降级使用 gpt2 编码器。

    计数规则（参考 OpenAI 的 Token 计数方式）：
    - 每条消息基础开销：4 Token。
    - 消息内容：按编码器实际计算的 Token 数。
    - 最终额外开销：3 Token（对话格式开销）。

    Args:
        messages: 消息列表（支持 dict 和 BaseMessage 混合类型）。

    Returns:
        int: 估算的 Token 总数。
    """
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
    except Exception:
        # 降级方案
        encoding = tiktoken.get_encoding("gpt2")

    num_tokens = 0
    for message in messages:
        # 每条消息的基础开销
        num_tokens += 4

        content = ""
        # 提取消息内容
        if isinstance(message, dict):
            content = message.get("content", "")
        elif hasattr(message, "content"):
            content = message.content

        # 计算内容的 Token 数
        if content:
            num_tokens += len(encoding.encode(str(content)))

    # 对话格式的额外开销
    num_tokens += 3
    return num_tokens


def prepare_messages(
    messages: List[Union[Message, BaseMessage, dict]],
    llm: BaseChatModel,
    system_prompt: str
) -> List[BaseMessage]:
    """
    准备发送给 LLM 的消息列表 - 这是消息处理的核心函数。

    处理流程（三步走）：
    1. 标准化：将混合类型（Pydantic Message、dict、BaseMessage）的消息
       统一转换为 LangChain 的 BaseMessage 对象。
       这步确保 ToolMessage 和 tool_calls 的上下文不丢失。

    2. 裁剪：根据 MAX_TOKENS 限制裁剪消息列表。
       使用 LangChain 的 trim_messages 函数，策略为：
       - strategy="last"：保留最后的消息（丢弃最早的消息）。
       - start_on="human"：确保裁剪后的第一条消息是用户消息。
       - include_system=False：System Prompt 在第 3 步单独添加。
       - allow_partial=False：不裁剪单条消息的部分内容。
       如果裁剪失败，降级为保留最后 10 条消息。

    3. 注入 System Prompt：在消息列表最前面插入 SystemMessage。

    Args:
        messages: 原始消息列表（可能包含多种类型）。
        llm: 目标 LLM 实例（用于 Token 计数）。
        system_prompt: 系统提示字符串。

    Returns:
        List[BaseMessage]: 准备好可以直接发送给 LLM 的消息列表。
    """
    # ================================================================
    # 步骤 1: 标准化 — 将混合类型的消息统一转为 BaseMessage 实例
    # ================================================================
    normalized_messages = []

    for msg in messages:
        # 情况 A: 已经是 LangChain BaseMessage 对象（保留所有细节）
        if isinstance(msg, BaseMessage):
            normalized_messages.append(msg)

        # 情况 B: Pydantic Message（前端传来的请求）
        elif isinstance(msg, Message):
            if msg.role == "user":
                normalized_messages.append(HumanMessage(content=msg.content))
            elif msg.role == "assistant":
                normalized_messages.append(AIMessage(content=msg.content))
            elif msg.role == "system":
                normalized_messages.append(SystemMessage(content=msg.content))

        # 情况 C: 字典（兜底方案，或 LangGraph Checkpoint 反序列化）
        elif isinstance(msg, dict):
            role = msg.get("role")
            content = msg.get("content", "")

            # 工具消息需要额外的 tool_call_id 以正确关联到 tool_calls
            if role == "tool":
                normalized_messages.append(ToolMessage(
                    content=content,
                    tool_call_id=msg.get("tool_call_id", "unknown")
                ))
            elif role == "user":
                normalized_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                # 简单 AIMessage 可能无法完全还原 tool_calls，
                # 但 LangGraph 内部通常直接传递 BaseMessage，这里作为兜底
                normalized_messages.append(AIMessage(content=content))
            elif role == "system":
                normalized_messages.append(SystemMessage(content=content))

    # ================================================================
    # 步骤 2: 裁剪 — 按 Token 限制裁剪消息，保留最相关的最近消息
    # ================================================================
    try:
        trimmed_messages = _trim_messages(
            normalized_messages,
            strategy="last",  # 保留最后的消息（最近的消息最重要）
            token_counter=get_token_count,
            max_tokens=settings.MAX_INPUT_TOKENS,
            start_on="human",  # 确保结果以用户消息开始
            include_system=False,  # System Prompt 在下一步单独添加
            allow_partial=False,  # 不裁剪部分消息内容
        )
    except Exception as e:
        # 裁剪失败时的降级策略：保留最后 10 条消息（简单但有效）
        logger.warning(
            "message_trimming_failed_fallback_enabled",
            error=str(e),
            total_messages=len(messages)
        )
        trimmed_messages = normalized_messages[-10:] if len(normalized_messages) > 10 else normalized_messages

    # ================================================================
    # 步骤 3: 注入 System Prompt — 在消息列表开头插入系统指令
    # ================================================================
    if system_prompt:
        trimmed_messages.insert(0, SystemMessage(content=system_prompt))

    return trimmed_messages
