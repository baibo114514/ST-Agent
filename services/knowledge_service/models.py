"""
Knowledge-service 数据模型。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Column, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class KnowledgeBase(SQLModel, table=True):
    __tablename__ = "te_knowledge_base"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    namespace: str = Field(nullable=False, max_length=64, index=True)
    name: str = Field(nullable=False, max_length=255, index=True)
    description: str | None = Field(default=None, sa_column=Column(Text))
    status: str = Field(default="active", max_length=32, index=True)
    search_policy_json: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    metadata_extraction_json: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    created_by: str = Field(default="system", max_length=128)
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=utc_now, nullable=False)


class KnowledgeDocument(SQLModel, table=True):
    __tablename__ = "te_knowledge_document"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    kb_id: str = Field(foreign_key="te_knowledge_base.id", index=True)
    source_type: str = Field(default="file", max_length=32, index=True)
    doc_kind: str = Field(default="body", max_length=32)
    title: str = Field(nullable=False, max_length=512, index=True)
    source_ref: str | None = Field(default=None, max_length=512)
    file_name: str | None = Field(default=None, max_length=512)
    mime_type: str | None = Field(default=None, max_length=128)
    file_size: int | None = Field(default=None)
    content_text: str | None = Field(default=None, sa_column=Column(Text))
    source_hash: str = Field(nullable=False, max_length=128, index=True)
    content_hash: str = Field(nullable=False, max_length=128, index=True)
    version: int = Field(default=1, nullable=False)
    ingest_status: str = Field(default="completed", max_length=32, index=True)
    ingest_error: str | None = Field(default=None, sa_column=Column(Text))
    chunk_count: int = Field(default=0, nullable=False)
    metadata_json: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    created_by: str = Field(default="system", max_length=128)
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=utc_now, nullable=False)


class KnowledgeChunk(SQLModel, table=True):
    __tablename__ = "td_knowledge_chunk"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    kb_id: str = Field(foreign_key="te_knowledge_base.id", index=True)
    document_id: str = Field(foreign_key="te_knowledge_document.id", index=True)
    chunk_index: int = Field(nullable=False)
    content_text: str = Field(sa_column=Column(Text, nullable=False))
    search_text: str | None = Field(default=None, sa_column=Column(Text))
    content_hash: str = Field(nullable=False, max_length=128, index=True)
    token_count: int | None = Field(default=None)
    metadata_json: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    status: str = Field(default="active", max_length=32, index=True)
    embedding: List[float] = Field(sa_type=Vector(1024))
    created_at: datetime = Field(default_factory=utc_now, nullable=False)


class KnowledgeIngestJob(SQLModel, table=True):
    __tablename__ = "tl_knowledge_ingest_job"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    kb_id: str = Field(foreign_key="te_knowledge_base.id", index=True)
    source_type: str = Field(default="file", max_length=32)
    source_json: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    source_hash: str | None = Field(default=None, max_length=128)
    status: str = Field(default="queued", max_length=32, index=True)
    submitted_by: str = Field(default="system", max_length=128)
    attempt_count: int = Field(default=0, nullable=False)
    error_message: str | None = Field(default=None, sa_column=Column(Text))
    result_json: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    trace_id: str | None = Field(default=None, max_length=128)
    started_at: datetime | None = Field(default=None)
    ended_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=utc_now, nullable=False)


class KnowledgeIngestStep(SQLModel, table=True):
    __tablename__ = "tl_knowledge_ingest_step"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    job_id: str = Field(foreign_key="tl_knowledge_ingest_job.id", index=True)
    step_name: str = Field(nullable=False, max_length=64)
    status: str = Field(nullable=False, max_length=32)
    summary_json: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    error_message: str | None = Field(default=None, sa_column=Column(Text))
    started_at: datetime | None = Field(default=None)
    ended_at: datetime | None = Field(default=None)
