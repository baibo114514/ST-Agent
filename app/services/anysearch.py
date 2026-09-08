"""
AnySearch 联网搜索客户端。

对齐参考项目 agent-paas/knowledge-service 的 anysearch_search：POST AnySearch API
（Bearer auth），返回 data.results 列表。复用持久 httpx.AsyncClient（与
knowledge_client 约定一致），无 Key 或请求失败时返回空列表，由调用方决定降级/兜底。

AnySearch 响应结构：
    {"data": {"results": [{"url", "title", "snippet"|"content"}, ...]}}
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.logging import logger


class AnySearchClient:
    """AnySearch 联网搜索异步客户端。"""

    def __init__(self) -> None:
        self.base_url = settings.ANYSEARCH_API_URL.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0))
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def search_web(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """联网搜索，返回 [{title, url, snippet}]。无 Key 或失败时返回空列表。"""
        if not settings.ANYSEARCH_API_KEY:
            return []
        count = max(1, min(top_k, 10))
        try:
            response = await self._get_client().post(
                self.base_url,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {settings.ANYSEARCH_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "query": query,
                    "zone": settings.ANYSEARCH_ZONE,
                    "language": settings.ANYSEARCH_LANGUAGE,
                    "max_results": count,
                },
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.exception("anysearch_request_failed", error=str(exc))
            return []

        data = payload.get("data") if isinstance(payload, dict) else None
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            return []

        items: List[Dict[str, Any]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            title = str(item.get("title") or "").strip()
            snippet = str(item.get("snippet") or item.get("content") or "").strip()
            items.append({"title": title, "url": url, "snippet": snippet})
        return items


anysearch_client = AnySearchClient()
