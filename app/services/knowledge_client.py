"""
Knowledge-service HTTP 客户端。

主后端不保存知识正文，也不直接访问知识库数据库。本客户端是 control-plane
访问独立 knowledge-service 的唯一适配层，负责服务间 Token、Trace、操作人
透传和错误收敛。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx
from fastapi import HTTPException, status

from app.core.config import settings
from app.core.logging import logger
from app.models.user import User


class KnowledgeServiceClient:
    """调用独立 knowledge-service 的异步客户端。"""

    def __init__(self) -> None:
        self.base_url = settings.KNOWLEDGE_SERVICE_BASE_URL.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        """获取或创建持久的 AsyncClient，复用连接避免每次新建的开销。"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout(), trust_env=False)
        return self._client

    async def close(self) -> None:
        """关闭持久连接（应用关闭时调用）。"""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _headers(self, actor: Optional[User] = None, trace_id: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "X-KB-Service-Token": settings.KNOWLEDGE_SERVICE_TOKEN,
        }
        if actor:
            headers["X-Actor-User-Id"] = str(actor.id)
            headers["X-Actor-Email"] = actor.email
        if trace_id:
            headers["X-Trace-Id"] = trace_id
        return headers

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=settings.KNOWLEDGE_SERVICE_CONNECT_TIMEOUT_SECONDS,
            timeout=settings.KNOWLEDGE_SERVICE_REQUEST_TIMEOUT_SECONDS,
        )

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _params(self, params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not params:
            return None
        return {key: value for key, value in params.items() if value not in (None, "")}

    async def request(
        self,
        method: str,
        path: str,
        *,
        actor: Optional[User] = None,
        trace_id: Optional[str] = None,
        json_body: Any = None,
        params: Optional[Dict[str, Any]] = None,
        files: Any = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Any:
        headers = self._headers(actor=actor, trace_id=trace_id)
        client = self._get_client()
        try:
            response = await client.request(
                method,
                self._url(path),
                headers=headers,
                json=json_body,
                params=self._params(params),
                files=files,
                data=data,
            )
        except httpx.HTTPError as exc:
            logger.exception("knowledge_service_request_failed", error=str(exc), path=path)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Knowledge service is unavailable",
            ) from exc

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            payload = response.json()
        else:
            payload = response.text

        if response.status_code >= 400:
            logger.warning(
                "knowledge_service_returned_error",
                status_code=response.status_code,
                path=path,
            )
            raise HTTPException(status_code=response.status_code, detail=payload)
        return payload

    async def get(self, path: str, *, actor: Optional[User] = None, params: Optional[Dict[str, Any]] = None) -> Any:
        return await self.request("GET", path, actor=actor, params=params)

    async def post_json(self, path: str, payload: Any, *, actor: Optional[User] = None) -> Any:
        return await self.request("POST", path, actor=actor, json_body=payload)

    async def put_json(self, path: str, payload: Any, *, actor: Optional[User] = None) -> Any:
        return await self.request("PUT", path, actor=actor, json_body=payload)

    async def post_empty(self, path: str, *, actor: Optional[User] = None) -> Any:
        return await self.request("POST", path, actor=actor)

    async def delete(
        self,
        path: str,
        *,
        actor: Optional[User] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        return await self.request("DELETE", path, actor=actor, params=params)

    async def post_multipart(
        self,
        path: str,
        *,
        actor: User,
        file_name: str,
        content_type: str,
        body: bytes,
        fields: Optional[Dict[str, Any]] = None,
    ) -> Any:
        files = {"file": (file_name, body, content_type or "application/octet-stream")}
        data = {key: value for key, value in (fields or {}).items() if value not in (None, "")}
        return await self.request("POST", path, actor=actor, files=files, data=data)


knowledge_service_client = KnowledgeServiceClient()
