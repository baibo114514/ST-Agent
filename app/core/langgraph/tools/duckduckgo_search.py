"""
DuckDuckGo 搜索工具 - 提供无需 API Key 的联网搜索能力。

本模块为 Agent 提供基础的网页搜索功能：
- 使用 DuckDuckGo 搜索引擎（免费、无需注册）。
- 每次搜索最多返回 10 条结果。
- 工具调用出错时自动返回错误信息而非抛出异常。

适用场景：
- 作为 AnySearch 搜索的降级方案（AnySearch API Key 未配置时）。
- 作为基础搜索工具始终开启。
- 对时效性要求一般的搜索需求。

与 AnySearch 搜索的区别：
    - DuckDuckGo: 免费、无需 API Key，但结果为原始网页摘要（噪声较多）。
    - AnySearch: 需要 API Key，但结果经过 AI 优化解析（噪声更少、相关性更高）。

工具配置：
    - num_results=10: 最多返回 10 条搜索结果。
    - handle_tool_error=True: 错误时自动返回错误信息（不崩溃）。
"""

from langchain_community.tools import DuckDuckGoSearchResults

# 创建 DuckDuckGo 搜索工具实例
# - num_results=10：每次搜索返回最多 10 条结果。
# - handle_tool_error=True：当网络错误或搜索失败时，
#   工具会自动捕获异常并返回错误描述字符串，而不会导致 Agent 执行中断。
duckduckgo_search_tool = DuckDuckGoSearchResults(
    num_results=10,
    handle_tool_error=True
)
