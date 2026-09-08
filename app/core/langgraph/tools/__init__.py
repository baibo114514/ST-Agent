"""
LangGraph 工具注册中心 - 统一管理和导出所有可用工具。

本模块是 LLM 工具的注册枢纽，负责：
1. 定义基础工具列表（当前为空，所有工具均按 feature flag 激活）。
2. 构建功能工具映射表（按 feature flag 名称 → 工具列表）。
3. 处理可选依赖（如 python_repl 需要 langchain_experimental）。

工具分类：
┌────────────────────┬────────────────────────────────────────────────┐
│ Feature Flag        │ 工具                                            │
├────────────────────┼────────────────────────────────────────────────┤
│ web_search          │ AnySearch 搜索（无 Key 降级 DuckDuckGo）          │
│ code_interpreter    │ Python REPL 代码沙盒（可选）                     │
│ memory_tools        │ SaveMemory + SearchMemory                       │
│ email_assistant     │ PrepareEmail + SendEmail（含审批中断）           │
│ knowledge_base      │ KnowledgeBaseSearch（按 Agent 绑定 kbIds 检索）  │
└────────────────────┴────────────────────────────────────────────────┘

工具激活流程：
    1. 前端请求 features: {"web_search": true, "email_assistant": true}。
    2. graph.py 的 _call_model 读取 active_features。
    3. 遍历 all_tools_map，收集匹配的工具。
    4. model.bind_tools(tools) 将工具注入 LLM 上下文。
    5. LLM 在需要时生成 tool_calls，ToolNode 执行对应工具。
"""

from langchain_core.tools import BaseTool
from app.core.logging import logger

# ============================================================================
# 导入所有工具实例
# ============================================================================

from .anysearch_search import anysearch_search_tool
from .memory_tools import save_memory_tool, search_memory_tool
from .email_tools import prepare_email_tool, send_email_tool
from .rag_tool import knowledge_base_tool
from .code_interpreter import python_repl_tool, PYTHON_REPL_AVAILABLE

# ============================================================================
# 基础工具（默认为空——所有工具均按 feature flag 按需激活）
# ============================================================================

# 联网搜索不再常驻：只有勾选「联网服务」（web_search）时才绑定 AnySearch；
# AnySearch 未配置 API Key 时会在其内部降级为 DuckDuckGo。
base_tools = []

# ============================================================================
# 功能工具注册表
# ============================================================================

# all_tools_map 将 feature flag 名称映射到对应的工具列表
# key: 与 FeatureFlags Schema 的字段名完全一致
# value: 该功能激活时绑定的工具列表
all_tools_map: dict[str, list[BaseTool]] = {
    # 联网搜索 — AnySearch（内部已实现无 API Key 时自动降级 DuckDuckGo）
    "web_search": [anysearch_search_tool],

    # 长期记忆 — Agent 可主动保存/检索用户偏好
    "memory_tools": [save_memory_tool, search_memory_tool],

    # 邮件助手 — 含 Human-in-the-loop 审批中断
    "email_assistant": [prepare_email_tool, send_email_tool],

    # 知识库检索 — 按 Agent 绑定的 kbIds 检索（kbIds 通过 InjectedState 注入）
    "knowledge_base": [knowledge_base_tool],
}

# ============================================================================
# 可选依赖注册
# ============================================================================

# 代码沙盒需要 langchain_experimental 包，未安装时跳过注册
if PYTHON_REPL_AVAILABLE and python_repl_tool is not None:
    all_tools_map["code_interpreter"] = [python_repl_tool]
    logger.info("code_interpreter_registered_in_tool_map")
else:
    logger.warning(
        "code_interpreter_not_available",
        hint="pip install langchain-experimental to enable",
    )

# 初始化完成日志
logger.info(
    "tool_registry_initialized",
    base_tool_count=len(base_tools),
    feature_keys=list(all_tools_map.keys()),
)

# 对外导出
__all__ = ["base_tools", "all_tools_map"]
