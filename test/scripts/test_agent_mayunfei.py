from __future__ import annotations

from typing import Any, cast
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.models.agent import PlatformAgent
from app.models.user import User
from app.schemas.agent import AgentKnowledgeConfig, PlatformAgentWrite
from app.services import agent_config as agent_config_module
from app.services.agent_config import AgentConfigService
from conftest import run_async

import ast
import inspect
from app.api.v1 import auth as auth_api
from app.api.v1 import sessions


def make_admin() -> User:
    return User(id=1, email="admin@example.com", hashed_password="not-used")


def make_command(**updates) -> PlatformAgentWrite:
    payload = {
        "agentCode": "course_agent",
        "name": "课程助手",
        "description": "非AI配置测试",
        "modelName": "deepseek-chat",
        "roleDescription": "回答课程相关问题",
        "features": {},
        "knowledge": {"enabled": False, "kbIds": [], "topK": 5, "scoreThreshold": 0},
        "config": {},
    }
    payload.update(updates)
    return PlatformAgentWrite.model_validate(payload)


def make_agent(**updates) -> PlatformAgent:
    values = {
        "id": "agent-1",
        "agent_code": "course_agent",
        "name": "课程助手",
        "description": "非AI配置测试",
        "model_name": "deepseek-chat",
        "role_description": "回答课程相关问题",
        "features_json": {},
        "config_json": {"knowledge": {"enabled": False, "kbIds": [], "topK": 5, "scoreThreshold": 0}},
        "version": 1,
        "status": "draft",
        "created_by": 1,
        "created_at": datetime.now(UTC).replace(tzinfo=None),
        "updated_at": datetime.now(UTC).replace(tzinfo=None),
    }
    values.update(updates)
    return PlatformAgent(**values)


async def immediate_to_thread(function, *args, **kwargs):
    return function(*args, **kwargs)


class FakeSession:
    def __init__(self, agent=None, *, commit_error: Exception | None = None, rows=None):
        self.agent = agent
        self.commit_error = commit_error
        self.rows = rows or []
        self.added = []
        self.statement: Any = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def add(self, value):
        self.added.append(value)
        if isinstance(value, PlatformAgent):
            self.agent = value

    def get(self, model, agent_id):
        return self.agent if self.agent and self.agent.id == agent_id else None

    def commit(self):
        if self.commit_error:
            raise self.commit_error

    def refresh(self, value):
        return None

    def exec(self, statement):
        self.statement = statement
        return SimpleNamespace(all=lambda: self.rows)


def install_fake_session(monkeypatch, fake_session: FakeSession):
    monkeypatch.setattr(agent_config_module.asyncio, "to_thread", immediate_to_thread)
    monkeypatch.setattr(agent_config_module, "Session", lambda engine: fake_session)


def _unlimited_route_functions(module):
    tree = ast.parse(inspect.getsource(module))
    missing = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        has_route = any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and isinstance(decorator.func.value, ast.Name)
            and decorator.func.value.id == "router"
            for decorator in node.decorator_list
        )
        has_limiter = any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and isinstance(decorator.func.value, ast.Name)
            and decorator.func.value.id == "limiter"
            and decorator.func.attr == "limit"
            for decorator in node.decorator_list
        )
        if has_route and not has_limiter:
            missing.append(node.name)
    return missing


def test_st_agent_001_create_agent_with_knowledge_disabled(monkeypatch):
    fake_session = FakeSession()
    install_fake_session(monkeypatch, fake_session)
    service = AgentConfigService()

    response = run_async(service.create_platform_agent(make_command(), make_admin()))

    assert response.status == "draft"
    assert response.version == 1
    assert response.knowledge.enabled is False
    assert response.knowledge.kb_ids == []
    assert len(fake_session.added) == 1


def test_st_agent_002_reject_invalid_agent_code():
    service = AgentConfigService()
    with pytest.raises(HTTPException) as exc_info:
        run_async(service._normalize_write(make_command(agentCode="bad.agent"), make_admin()))
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Agent code format is invalid"


def test_st_agent_003_reject_duplicate_agent_code(monkeypatch):
    fake_session = FakeSession(commit_error=SQLAlchemyError("duplicate"))
    install_fake_session(monkeypatch, fake_session)
    service = AgentConfigService()

    with pytest.raises(HTTPException) as exc_info:
        run_async(service.create_platform_agent(make_command(), make_admin()))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Agent code already exists"


def test_st_agent_004_require_kb_ids_when_knowledge_enabled():
    service = AgentConfigService()
    command = make_command(knowledge={"enabled": True, "kbIds": [], "topK": 5, "scoreThreshold": 0})

    with pytest.raises(HTTPException) as exc_info:
        run_async(service._normalize_write(command, make_admin()))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Knowledge bases are required"


def test_st_agent_005_reject_more_than_ten_bound_knowledge_bases():
    kb_ids = [f"kb-{index}" for index in range(11)]
    with pytest.raises(ValidationError, match="at most 10"):
        AgentKnowledgeConfig(enabled=True, kbIds=kb_ids)


def test_st_agent_006_reject_inactive_or_missing_knowledge_base(monkeypatch):
    service = AgentConfigService()
    monkeypatch.setattr(
        agent_config_module.knowledge_service_client,
        "get",
        AsyncMock(return_value={"items": [{"id": "kb-1", "status": "active"}]}),
    )
    command = make_command(
        knowledge={"enabled": True, "kbIds": ["kb-1", "kb-archived"], "topK": 5, "scoreThreshold": 0}
    )

    with pytest.raises(HTTPException) as exc_info:
        run_async(service._normalize_write(command, make_admin()))

    assert exc_info.value.status_code == 400
    detail = cast(dict[str, Any], exc_info.value.detail)
    assert detail["message"] == "Knowledge base is not active"
    assert detail["kbIds"] == ["kb-archived"]


def test_st_agent_007_update_increments_version(monkeypatch):
    agent = make_agent(version=1)
    fake_session = FakeSession(agent=agent)
    install_fake_session(monkeypatch, fake_session)
    service = AgentConfigService()

    response = run_async(
        service.update_platform_agent("agent-1", make_command(name="更新后的名称"), make_admin())
    )

    assert response.name == "更新后的名称"
    assert response.version == 2
    assert response.created_by == 1


def test_st_agent_008_update_unknown_agent_returns_404(monkeypatch):
    install_fake_session(monkeypatch, FakeSession(agent=None))
    service = AgentConfigService()

    with pytest.raises(HTTPException) as exc_info:
        run_async(service.update_platform_agent("missing", make_command(), make_admin()))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Agent not found"


def test_st_agent_009_first_publish_records_published_time(monkeypatch):
    agent = make_agent(status="draft", published_at=None)
    fake_session = FakeSession(agent=agent)
    install_fake_session(monkeypatch, fake_session)
    service = AgentConfigService()

    response = run_async(service.change_status("agent-1", "published", make_admin()))

    assert response.status == "published"
    assert response.published_at is not None


def test_st_agent_010_offline_agent_cannot_be_called(monkeypatch):
    agent = make_agent(status="offline")
    install_fake_session(monkeypatch, FakeSession(agent=agent))
    service = AgentConfigService()

    with pytest.raises(HTTPException) as exc_info:
        run_async(service.get_published_agent("agent-1"))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Agent not found"


def test_st_agent_011_all_session_routes_have_rate_limits():
    assert _unlimited_route_functions(sessions) == []


def test_st_agent_012_all_auth_routes_have_rate_limits():
    assert _unlimited_route_functions(auth_api) == []


def test_st_agent_013_public_list_query_only_selects_published(monkeypatch):
    published = make_agent(status="published")
    fake_session = FakeSession(rows=[published])
    install_fake_session(monkeypatch, fake_session)
    service = AgentConfigService()

    items = run_async(service.list_public_agents())

    sql = str(fake_session.statement.compile(compile_kwargs={"literal_binds": True}))
    assert "platform_agent.status = 'published'" in sql
    assert len(items) == 1
    public_payload = items[0].model_dump(by_alias=True)
    assert "roleDescription" not in public_payload
    assert "config" not in public_payload
    assert "createdBy" not in public_payload
