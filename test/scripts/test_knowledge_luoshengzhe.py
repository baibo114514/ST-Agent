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


def test_st_kb_006_reject_duplicate_active_name_case_insensitively():
    existing = KnowledgeBase(id="kb-old", namespace="default", name="CourseKB", created_by="1")
    session = make_session(scalar_values=[existing])

    with pytest.raises(HTTPException) as exc_info:
        run_async(kb_service.create_base(session, {"name": "coursekb", "namespace": "default"}, "1"))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "KB_NAME_EXISTS"
    session.add.assert_not_called()


def test_st_kb_007_reject_non_object_search_policy():
    kb = KnowledgeBase(id="kb-1", namespace="default", name="KB", created_by="1")
    session = make_session(scalar_values=[kb])

    with pytest.raises(HTTPException) as exc_info:
        run_async(kb_service.update_base(session, "kb-1", {"searchPolicyJson": "vector"}))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "INVALID_POLICY"
    session.commit.assert_not_awaited()


def test_st_kb_008_archive_and_restore_lifecycle():
    kb = KnowledgeBase(id="kb-1", namespace="default", name="KB", created_by="1")
    session = make_session(scalar_values=[kb, kb])

    archived = run_async(kb_service.archive_base(session, "kb-1", archived=True))
    restored = run_async(kb_service.archive_base(session, "kb-1", archived=False))

    assert archived["status"] == "archived"
    assert restored["status"] == "active"
    assert session.commit.await_count == 2


def test_st_kb_009_include_archived_changes_list_filter():
    active_session = make_session(scalar_values=[0])
    active_session.execute.return_value = EmptyScalarResult()
    all_session = make_session(scalar_values=[0])
    all_session.execute.return_value = EmptyScalarResult()

    run_async(kb_service.list_bases(active_session, include_archived=False))
    run_async(kb_service.list_bases(all_session, include_archived=True))

    active_sql = str(active_session.scalar.await_args.args[0])
    all_sql = str(all_session.scalar.await_args.args[0])
    assert "te_knowledge_base.status" in active_sql
    assert "te_knowledge_base.status" not in all_sql


def test_st_kb_010_pagination_clamps_page_and_page_size():
    assert kb_service._paginate_query(0, 101) == (1, 100)


def test_st_kb_011_document_list_uses_metadata_filters_not_body_scan():
    kb = KnowledgeBase(id="kb-1", namespace="default", name="KB", created_by="1")
    session = make_session(scalar_values=[kb, 0])
    session.execute.return_value = EmptyScalarResult()

    result = run_async(
        kb_service.list_documents(
            session,
            "kb-1",
            include_archived=False,
            keyword="政策",
            source_type="file",
        )
    )

    count_sql = str(session.scalar.await_args_list[1].args[0])
    assert "te_knowledge_document.title" in count_sql
    assert "te_knowledge_document.source_ref" in count_sql
    assert "te_knowledge_document.file_name" in count_sql
    assert "te_knowledge_document.content_text" not in count_sql
    assert "te_knowledge_document.source_type" in count_sql
    assert "te_knowledge_document.ingest_status" in count_sql
    assert result["items"] == []

def test_st_kb_012_extract_utf8_text_without_corruption():
    result = extract_text_from_bytes("政策.txt", "text/plain", "武汉扶持政策".encode("utf-8"))
    assert result == {
        "title": "政策.txt",
        "contentText": "武汉扶持政策",
        "pages": 0,
        "metadata": {},
    }


def test_st_kb_013_extract_and_strip_markdown_metadata():
    text = "# 测试政策\n- **地区**：武汉\n- 年份：2026\n---\n正文内容"
    result = extract_markdown_front_matter(text)

    assert result["title"] == "测试政策"
    assert result["metadata"]["地区"] == "武汉"
    assert result["metadata"]["年份"] == "2026"
    assert result["metadata"]["title"] == "测试政策"
    assert result["contentText"] == "正文内容"
    assert result["sourceType"] == "markdown_metadata_block"


def test_st_kb_014_reject_unsupported_binary_file():
    with pytest.raises(HTTPException) as exc_info:
        extract_text_from_bytes("sample.exe", "application/octet-stream", b"binary")
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "UNSUPPORTED_FILE"


def test_st_kb_015_single_chunk_at_size_boundary(monkeypatch):
    monkeypatch.setattr(kb_service.settings, "chunk_size", 100)
    monkeypatch.setattr(kb_service.settings, "chunk_overlap", 0)
    content = "x" * 97

    chunks = kb_service.chunk_text("T", content)

    assert chunks == ["T\n\n" + content]
    assert len(chunks[0]) == 100

def test_st_kb_016_rename_to_existing_name_should_be_rejected():
    # 缺陷复现：先创建知识库 A，再创建知识库 B，然后把 B 重命名为 A。
    # 当前 update_base 未做重名校验（create_base 有，update_base 没有），
    # 重命名会成功，导致同一 namespace 下两个 active 知识库同名。
    # 正确行为：应抛 409 KB_NAME_EXISTS。本用例当前会 FAIL（DID NOT RAISE），
    # 待 update_base 补上重名冲突校验后应转绿。
    kb_a = KnowledgeBase(id="kb-a", namespace="default", name="A", created_by="1")
    kb_b = KnowledgeBase(id="kb-b", namespace="default", name="B", created_by="1")
    # 第一次 scalar 返回被更新的 B（get_kb），第二次返回重名冲突的 A（缺失的重名校验查询）
    session = make_session(scalar_values=[kb_b, kb_a])

    with pytest.raises(HTTPException) as exc_info:
        run_async(kb_service.update_base(session, "kb-b", {"name": "A"}))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "KB_NAME_EXISTS"