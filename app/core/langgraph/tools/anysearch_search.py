"""
AnySearch 联网搜索工具 - 专为 AI Agent 设计的联网搜索。

本模块为 Agent 提供联网搜索能力，使用 AnySearch API（Bearer auth）：

AnySearch 相比 DuckDuckGo 的优势：
    - 专为 AI 设计：返回结构化的搜索结果，噪声更少。
    - 支持 zone / language 配置（中文区默认 cn / zh-CN）。
    - 稳定性更好。

降级策略：
    如果 ANYSEARCH_API_KEY 环境变量未配置，自动降级为 DuckDuckGo 搜索。
    这确保即使没有 API Key，Agent 仍然具备基础搜索能力。
"""

from typing import Any, Dict, List

from langchain_core.tools import tool

from app.core.config import settings
from app.core.logging import logger
from app.services.anysearch import anysearch_client


def _format_anysearch_results(query: str, items: List[Dict[str, Any]]) -> str:
    if not items:
        return f"未找到「{query}」相关的联网搜索结果。"
    lines = [f"联网搜索「{query}」的结果："]
    for index, item in enumerate(items, start=1):
        title = item.get("title") or item.get("url") or "Untitled"
        url = item.get("url") or ""
        snippet = item.get("snippet") or ""
        lines.append(f"{index}. {title}\n   {snippet}\n   {url}")
    return "\n".join(lines)


if settings.ANYSEARCH_API_KEY:
    # 配置了 AnySearch API Key → 使用 AnySearch 搜索
    @tool
    async def anysearch_search_tool(query: str) -> str:
        """使用 AnySearch 搜索引擎查询最新的互联网信息。

        当需要了解最新事件、实时数据或验证信息时使用此工具。
        输入：搜索查询字符串。输出：相关网页标题、摘要和链接。
        """
        items = await anysearch_client.search_web(query, top_k=5)
        return _format_anysearch_results(query, items)

    logger.info("anysearch_search_tool_initialized")
else:
    # 未配置 API Key → 降级为 DuckDuckGo 搜索（免费模式）
    logger.warning("anysearch_api_key_not_configured_falling_back_to_duckduckgo")
    from langchain_community.tools import DuckDuckGoSearchResults

    anysearch_search_tool = DuckDuckGoSearchResults(
        num_results=5,
        handle_tool_error=True,
        description=(
            "使用 DuckDuckGo 搜索引擎查询互联网信息（降级方案）。"
            "输入：搜索查询字符串。输出：相关网页摘要列表。"
        ),
    )
