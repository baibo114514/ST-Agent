from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.api.v1 import admin as admin_api
from app.models.user import User
from services.knowledge_service import security as kb_security
from services.knowledge_service import service as kb_service
from services.knowledge_service.extractors import extract_markdown_front_matter, extract_text_from_bytes
from services.knowledge_service.metadata import normalize_metadata, parse_metadata
from services.knowledge_service.models import KnowledgeBase
from conftest import run_async


def make_admin() -> User:
    return User(id=1, email="admin@example.com", hashed_password="not-used")


def make_session(*, scalar_values=()):
    return SimpleNamespace(
        scalar=AsyncMock(side_effect=list(scalar_values)),
        execute=AsyncMock(),
        add=Mock(),
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )


class EmptyScalarResult:
    def scalars(self):
        return self

    def all(self):
        return []


def test_st_kb_001_internal_api_requires_service_token(monkeypatch):
    monkeypatch.setattr(kb_security.settings, "service_token", "correct-token")
    with pytest.raises(HTTPException) as exc_info:
        kb_security.require_service_token(None)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["code"] == "INVALID_TOKEN"


def test_st_kb_002_internal_api_rejects_wrong_service_token(monkeypatch):
    monkeypatch.setattr(kb_security.settings, "service_token", "correct-token")
    with pytest.raises(HTTPException) as exc_info:
        kb_security.require_service_token("wrong-token")
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["code"] == "INVALID_TOKEN"


def test_st_kb_003_admin_proxy_creates_active_knowledge_base(monkeypatch):
    expected = {
        "id": "kb-1",
        "name": "课程测试库",
        "namespace": "default",
        "status": "active",
        "createdBy": "1",
    }
    post_mock = AsyncMock(return_value=expected)
    monkeypatch.setattr(admin_api.knowledge_service_client, "post_json", post_mock)
    payload = {"name": "课程测试库", "namespace": "default"}

    result = run_async(
        admin_api.create_knowledge_base.__wrapped__(None, payload, make_admin())
    )

    assert result == expected
    post_mock.assert_awaited_once_with("/internal/v1/kb/bases", payload, actor=ANY)


def test_st_kb_004_reject_blank_knowledge_base_name():
    session = make_session()
    with pytest.raises(HTTPException) as exc_info:
        run_async(kb_service.create_base(session, {"name": "   ", "namespace": "default"}, "1"))
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "INVALID_NAME"
    session.add.assert_not_called()


def test_st_kb_005_reject_unknown_namespace(monkeypatch):
    monkeypatch.setattr(kb_service.settings, "allowed_namespaces", ["default", "policy"])
    with pytest.raises(HTTPException) as exc_info:
        run_async(kb_service.create_base(make_session(), {"name": "KB", "namespace": "unknown"}, "1"))
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "INVALID_NAMESPACE"


