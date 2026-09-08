"""
Knowledge-service 服务间认证。
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Header, HTTPException, status

from services.knowledge_service.config import settings


def require_service_token(x_kb_service_token: Annotated[str | None, Header()] = None) -> None:
    if not settings.service_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "TOKEN_NOT_CONFIGURED", "message": "knowledge service token is not configured"},
        )
    if not x_kb_service_token or not secrets.compare_digest(x_kb_service_token, settings.service_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": "invalid knowledge service token"},
        )


def actor_from_headers(
    x_actor_user_id: Annotated[str | None, Header()] = None,
    x_actor_email: Annotated[str | None, Header()] = None,
) -> str:
    return (x_actor_user_id or x_actor_email or "system").strip()[:128] or "system"
