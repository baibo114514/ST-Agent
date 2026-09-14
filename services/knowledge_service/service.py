"""
Knowledge-service 业务逻辑。
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections import OrderedDict
from math import ceil
from datetime import UTC, datetime
from typing import Any, Dict, List

import httpx
from fastapi import HTTPException, status
from langchain_openai import OpenAIEmbeddings
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from services.knowledge_service.config import settings
from services.knowledge_service.db import AsyncSessionLocal
from services.knowledge_service.extractors import extract_text_from_bytes
from services.knowledge_service.metadata import (
    default_metadata_extraction_config,
    normalize_metadata,
    normalize_metadata_extraction_config,
    tokenize_for_search,
)
from services.knowledge_service.models import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeIngestJob,
    KnowledgeIngestStep,
)


TERMINAL_JOB_STATUSES = {"completed", "partial_completed", "failed", "canceled"}
SENTENCE_BOUNDARY_RE = re.compile(r"[^。！？!?；;.]+[。！？!?；;.]?")
PARAGRAPH_BOUNDARY_RE = re.compile(r"\n\s*\n+")

# 查询向量缓存容量：命中时避免 Ollama 往返，容量限制防止内存膨胀。
# 复用的外部服务客户端：embedding 与 rerank 都走持久连接，避免每次检索重建连接
# （与 knowledge_client 复用持久 httpx.AsyncClient 的约定一致）。
_embeddings_client: OpenAIEmbeddings | None = None
_rerank_client: httpx.AsyncClient | None = None
# 查询向量 LRU 缓存；大小由 settings.embedding_cache_size 控制（设为 0 关闭）。
_embedding_cache: OrderedDict[str, List[float]] = OrderedDict()


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def problem(http_status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=http_status, detail={"code": code, "message": message})


def normalize_namespace(value: Any) -> str:
    namespace = str(value or "default").strip()
    if namespace not in settings.allowed_namespaces:
        allowed = ", ".join(settings.allowed_namespaces)
        raise problem(status.HTTP_400_BAD_REQUEST, "INVALID_NAMESPACE", f"namespace must be one of: {allowed}")
    return namespace


def source_hash(blob_sha256: str, source_ref: str | None) -> str:
    normalized = (source_ref or "").strip()
    if normalized:
        return f"file-ref:{sha256_text(normalized)}"
    return f"file:{blob_sha256}"


def _hard_split_text(text: str, max_chars: int) -> List[str]:
    return [
        text[cursor : cursor + max_chars].strip()
        for cursor in range(0, len(text), max_chars)
        if text[cursor : cursor + max_chars].strip()
    ]


def _pack_units(units: List[str], max_chars: int, separator: str) -> List[str]:
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0
    separator_len = len(separator)

    for unit in units:
        normalized = unit.strip()
        if not normalized:
            continue
        if len(normalized) > max_chars:
            if current:
                chunks.append(separator.join(current).strip())
                current = []
                current_len = 0
            chunks.extend(_hard_split_text(normalized, max_chars))
            continue

        next_len = current_len + len(normalized) + (separator_len if current else 0)
        if current and next_len > max_chars:
            chunks.append(separator.join(current).strip())
            current = [normalized]
            current_len = len(normalized)
        else:
            current.append(normalized)
            current_len = next_len

    if current:
        chunks.append(separator.join(current).strip())
    return chunks


def _split_long_block(text: str, max_chars: int) -> List[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > 1:
        line_units: List[str] = []
        for line in lines:
            if len(line) <= max_chars:
                line_units.append(line)
            else:
                line_units.extend(_split_long_block(line, max_chars))
        return _pack_units(line_units, max_chars, "\n")

    sentence_units = [
        match.group(0).strip()
        for match in SENTENCE_BOUNDARY_RE.finditer(text)
        if match.group(0).strip()
    ]
    if not sentence_units:
        sentence_units = [text.strip()]

    split_units: List[str] = []
    for sentence in sentence_units:
        if len(sentence) <= max_chars:
            split_units.append(sentence)
        else:
            split_units.extend(_hard_split_text(sentence, max_chars))
    return _pack_units(split_units, max_chars, "")


def _overlap_tail(text: str, overlap_chars: int) -> str:
    if overlap_chars <= 0 or len(text) <= overlap_chars:
        return ""
    tail = text[-overlap_chars:].strip()
    for index, char in enumerate(tail):
        if char in "\n。！？!?；;.":
            trimmed = tail[index + 1 :].strip()
            if trimmed:
                return trimmed
    return tail


def _apply_chunk_overlap(chunks: List[str]) -> List[str]:
    overlap_chars = max(0, min(settings.chunk_overlap, settings.chunk_size // 2))
    if overlap_chars <= 0 or len(chunks) <= 1:
        return chunks

    overlapped = [chunks[0]]
    for previous, chunk in zip(chunks, chunks[1:]):
        tail = _overlap_tail(previous, overlap_chars)
        overlapped.append(f"{tail}\n\n{chunk}" if tail else chunk)
    return overlapped


def chunk_text(title: str, content: str) -> List[str]:
    max_chars = max(100, settings.chunk_size)
    text = f"{title}\n\n{content}".replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    paragraphs = [paragraph.strip() for paragraph in PARAGRAPH_BOUNDARY_RE.split(text) if paragraph.strip()]
    units: List[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= max_chars:
            units.append(paragraph)
        else:
            units.extend(_split_long_block(paragraph, max_chars))

    chunks = _pack_units(units, max_chars, "\n\n")
    return _apply_chunk_overlap(chunks)


def _get_embeddings_client() -> OpenAIEmbeddings:
    """获取或创建复用的 embedding 客户端，避免每次检索重建连接。"""
    global _embeddings_client
    if _embeddings_client is None:
        _embeddings_client = OpenAIEmbeddings(
            model=settings.embedding_model,
            openai_api_key=settings.embedding_api_key,
            openai_api_base=settings.embedding_base_url,
            check_embedding_ctx_length=False,
        )
    return _embeddings_client


def _get_rerank_client() -> httpx.AsyncClient:
    """获取或创建复用的 rerank HTTP 客户端，避免每次检索新建连接。"""
    global _rerank_client
    if _rerank_client is None or _rerank_client.is_closed:
        _rerank_client = httpx.AsyncClient(timeout=15.0)
    return _rerank_client


async def close_rerank_client() -> None:
    """关闭 rerank 持久连接（应用关闭时调用）。"""
    global _rerank_client
    if _rerank_client is not None and not _rerank_client.is_closed:
        await _rerank_client.aclose()
    _rerank_client = None


def _cached_embedding(text: str) -> List[float] | None:
    key = text.strip()
    if key in _embedding_cache:
        vector = _embedding_cache.pop(key)
        _embedding_cache[key] = vector
        return vector
    return None


def _cache_embedding(text: str, vector: List[float]) -> None:
    key = text.strip()
    if not key:
        return
    _embedding_cache[key] = vector
    _embedding_cache.move_to_end(key)
    while len(_embedding_cache) > settings.embedding_cache_size:
        _embedding_cache.popitem(last=False)


async def get_embedding(text: str) -> List[float]:
    if settings.embedding_cache_size > 0:
        cached = _cached_embedding(text)
        if cached is not None:
            return cached
    embeddings = await get_embeddings([text])
    vector = embeddings[0]
    if settings.embedding_cache_size > 0:
        _cache_embedding(text, vector)
    return vector


async def get_embeddings(texts: List[str]) -> List[List[float]]:
    if not settings.embedding_api_key:
        raise problem(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "EMBEDDING_NOT_CONFIGURED",
            "knowledge embedding API key is not configured",
        )
    if not texts:
        return []
    cleaned_texts = [text if text else " " for text in texts]
    embeddings = _get_embeddings_client()
    try:
        vectors = await embeddings.aembed_documents(cleaned_texts, chunk_size=settings.embedding_batch_size)
    except Exception as exc:
        logger.exception(
            "knowledge_embedding_failed",
            error=str(exc),
            embedding_model=settings.embedding_model,
            embedding_base_url=settings.embedding_base_url,
        )
        raise problem(
            status.HTTP_502_BAD_GATEWAY,
            "EMBEDDING_FAILED",
            "knowledge embedding provider request failed",
        ) from exc
    if len(vectors) != len(cleaned_texts):
        raise problem(
            status.HTTP_502_BAD_GATEWAY,
            "EMBEDDING_COUNT_MISMATCH",
            "knowledge embedding provider returned unexpected vector count",
        )
    return vectors


async def rerank_items(query: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not items or not settings.reranker_api_key:
        return items
    if len(items) <= 1:
        return items
    documents = [str(item.get("contentExcerpt") or "") for item in items]
    payload = {
        "model": settings.reranker_model,
        "query": query,
        "documents": documents,
        "top_n": len(documents),
        "return_documents": False,
    }
    headers = {
        "Authorization": f"Bearer {settings.reranker_api_key}",
        "Content-Type": "application/json",
    }
    try:
        response = await _get_rerank_client().post(
            f"{settings.reranker_base_url.rstrip('/')}/rerank",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.exception("knowledge_rerank_failed", error=str(exc))
        return items

    ordered = []
    for result in data.get("results", []):
        index = result.get("index")
        if isinstance(index, int) and 0 <= index < len(items):
            item = dict(items[index])
            item["rerankScore"] = result.get("relevance_score")
            ordered.append(item)
    return ordered or items


def kb_item(kb: KnowledgeBase, document_count: int = 0, chunk_count: int = 0, failed_job_count: int = 0) -> Dict[str, Any]:
    return {
        "id": kb.id,
        "namespace": kb.namespace,
        "name": kb.name,
        "description": kb.description,
        "status": kb.status,
        "searchPolicyJson": kb.search_policy_json,
        "metadataExtractionJson": kb.metadata_extraction_json or default_metadata_extraction_config(),
        "documentCount": document_count,
        "chunkCount": chunk_count,
        "failedJobCount": failed_job_count,
        "createdBy": kb.created_by,
        "createdAt": iso(kb.created_at),
        "updatedAt": iso(kb.updated_at),
    }


def document_item(document: KnowledgeDocument) -> Dict[str, Any]:
    return {
        "id": document.id,
        "kbId": document.kb_id,
        "sourceType": document.source_type,
        "docKind": document.doc_kind,
        "title": document.title,
        "sourceRef": document.source_ref,
        "fileName": document.file_name,
        "mimeType": document.mime_type,
        "fileSize": document.file_size,
        "contentExcerpt": (document.content_text or "")[:500],
        "ingestStatus": document.ingest_status,
        "ingestError": document.ingest_error,
        "chunkCount": document.chunk_count,
        "version": document.version,
        "lastIngestJobId": None,
        "metadataJson": document.metadata_json,
        "createdBy": document.created_by,
        "createdAt": iso(document.created_at),
        "updatedAt": iso(document.updated_at),
    }


def job_item(job: KnowledgeIngestJob, steps: List[KnowledgeIngestStep] | None = None) -> Dict[str, Any]:
    source = job.source_json or {}
    result = job.result_json or {}
    document_effects = result.get("documentEffects")
    if not isinstance(document_effects, list):
        document_effects = []
    payload = {
        "id": job.id,
        "kbId": job.kb_id,
        "sourceType": job.source_type,
        "sourceSummary": source.get("sourceSummary") or job.source_type,
        "sourceHash": job.source_hash,
        "status": job.status,
        "submittedBy": job.submitted_by,
        "attemptCount": job.attempt_count,
        "traceId": job.trace_id,
        "errorMessage": job.error_message,
        "resultJson": result,
        "documentEffects": document_effects,
        "startedAt": iso(job.started_at),
        "endedAt": iso(job.ended_at),
        "createdAt": iso(job.created_at),
        "updatedAt": iso(job.updated_at),
    }
    if steps is not None:
        payload["steps"] = [
            {
                "id": step.id,
                "jobId": step.job_id,
                "stepName": step.step_name,
                "status": step.status,
                "summary": step.summary_json,
                "errorMessage": step.error_message,
                "startedAt": iso(step.started_at),
                "endedAt": iso(step.ended_at),
            }
            for step in steps
        ]
    return payload


async def add_step(
    session: AsyncSession,
    job: KnowledgeIngestJob,
    name: str,
    status_value: str,
    summary: Dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    now = utc_now()
    session.add(
        KnowledgeIngestStep(
            job_id=job.id,
            step_name=name,
            status=status_value,
            summary_json=summary or {},
            error_message=error,
            started_at=now,
            ended_at=now,
        )
    )
    await session.flush()


async def get_kb(session: AsyncSession, kb_id: str, include_archived: bool = False) -> KnowledgeBase:
    conditions = [KnowledgeBase.id == kb_id]
    if not include_archived:
        conditions.append(KnowledgeBase.status == "active")
    kb = await session.scalar(select(KnowledgeBase).where(*conditions))
    if not kb:
        raise problem(status.HTTP_404_NOT_FOUND, "KB_NOT_FOUND", "knowledge base not found")
    return kb


async def get_base(session: AsyncSession, kb_id: str, include_archived: bool = False) -> Dict[str, Any]:
    kb = await get_kb(session, kb_id, include_archived=include_archived)
    document_count = await session.scalar(
        select(func.count()).select_from(KnowledgeDocument).where(
            KnowledgeDocument.kb_id == kb.id,
            KnowledgeDocument.ingest_status != "archived",
        )
    )
    chunk_count = await session.scalar(
        select(func.count()).select_from(KnowledgeChunk).where(
            KnowledgeChunk.kb_id == kb.id,
            KnowledgeChunk.status == "active",
        )
    )
    failed_job_count = await session.scalar(
        select(func.count()).select_from(KnowledgeIngestJob).where(
            KnowledgeIngestJob.kb_id == kb.id,
            KnowledgeIngestJob.status == "failed",
        )
    )
    return kb_item(kb, int(document_count or 0), int(chunk_count or 0), int(failed_job_count or 0))


def ingest_error_message(exc: Exception) -> str:
    detail = exc.detail if isinstance(exc, HTTPException) else type(exc).__name__
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("code") or "ingest failed")
    return str(detail)


async def create_ingest_job(
    kb_id: str,
    *,
    file_name: str,
    mime_type: str | None,
    size_bytes: int,
    title: str | None,
    source_ref: str | None,
    file_source_hash: str,
    actor: str,
    trace_id: str | None,
) -> tuple[str, str, str, Dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        kb = await get_kb(session, kb_id)
        now = utc_now()
        job = KnowledgeIngestJob(
            kb_id=kb.id,
            source_type="file",
            source_json={
                "sourceSummary": f"file:{file_name}",
                "fileName": file_name,
                "mimeType": mime_type,
                "sizeBytes": size_bytes,
                "title": title,
                "sourceRef": source_ref,
            },
            source_hash=file_source_hash,
            status="running",
            submitted_by=actor,
            attempt_count=1,
            trace_id=trace_id,
            started_at=now,
            updated_at=now,
        )
        session.add(job)
        await session.flush()
        await add_step(session, job, "validate", "succeeded", {"fileName": file_name, "sizeBytes": size_bytes})
        await session.commit()
        return kb.id, job.id, kb.namespace, kb.metadata_extraction_json or default_metadata_extraction_config()


async def record_job_step(
    job_id: str,
    name: str,
    status_value: str,
    summary: Dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    async with AsyncSessionLocal() as session:
        job = await session.scalar(select(KnowledgeIngestJob).where(KnowledgeIngestJob.id == job_id))
        if not job:
            raise problem(status.HTTP_404_NOT_FOUND, "JOB_NOT_FOUND", "knowledge ingest job not found")
        await add_step(session, job, name, status_value, summary, error)
        job.updated_at = utc_now()
        session.add(job)
        await session.commit()


async def get_existing_document_state(kb_id: str, file_source_hash: str) -> Dict[str, Any] | None:
    async with AsyncSessionLocal() as session:
        document = await session.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.kb_id == kb_id,
                KnowledgeDocument.source_hash == file_source_hash,
            )
        )
        if not document:
            return None
        return {
            "id": document.id,
            "contentHash": document.content_hash,
            "ingestStatus": document.ingest_status,
            "chunkCount": document.chunk_count,
        }


async def complete_ingest_job(
    kb_id: str,
    job_id: str,
    *,
    file_name: str,
    mime_type: str | None,
    size_bytes: int,
    normalized_title: str,
    source_ref: str | None,
    file_source_hash: str,
    content_hash: str,
    content: str,
    metadata_json: Dict[str, Any],
    actor: str,
    chunks: List[str],
    embeddings: List[List[float]],
) -> str:
    async with AsyncSessionLocal() as session:
        kb = await get_kb(session, kb_id)
        job = await session.scalar(select(KnowledgeIngestJob).where(KnowledgeIngestJob.id == job_id))
        if not job:
            raise problem(status.HTTP_404_NOT_FOUND, "JOB_NOT_FOUND", "knowledge ingest job not found")

        document = await session.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.kb_id == kb.id,
                KnowledgeDocument.source_hash == file_source_hash,
            )
        )
        before_hash = document.content_hash if document else None
        operation = "created"

        if document and document.content_hash == content_hash and document.ingest_status == "completed":
            operation = "unchanged"
            chunk_count = document.chunk_count
        else:
            if not chunks:
                raise problem(
                    status.HTTP_409_CONFLICT,
                    "DOCUMENT_CHANGED_DURING_INGEST",
                    "document changed during ingest; retry upload",
                )
            if len(chunks) != len(embeddings):
                raise problem(
                    status.HTTP_502_BAD_GATEWAY,
                    "EMBEDDING_COUNT_MISMATCH",
                    "knowledge embedding provider returned unexpected vector count",
                )
            if document:
                operation = "updated"
                document.version += 1
                await session.execute(
                    delete(KnowledgeChunk).where(
                        KnowledgeChunk.document_id == document.id,
                        KnowledgeChunk.kb_id == kb.id,
                    )
                )
            else:
                document = KnowledgeDocument(
                    kb_id=kb.id,
                    source_type="file",
                    doc_kind="body",
                    title=normalized_title,
                    source_hash=file_source_hash,
                    content_hash=content_hash,
                    created_by=actor,
                )
                session.add(document)
                await session.flush()

            for index, chunk in enumerate(chunks):
                session.add(
                    KnowledgeChunk(
                        kb_id=kb.id,
                        document_id=document.id,
                        chunk_index=index,
                        content_text=chunk,
                        search_text=tokenize_for_search(chunk),
                        content_hash=sha256_text(chunk),
                        token_count=max(1, len(chunk) // 4),
                        metadata_json={
                            "title": normalized_title,
                            "fileName": file_name,
                            "sourceRef": source_ref,
                        },
                        embedding=embeddings[index],
                    )
                )
            chunk_count = len(chunks)
            document.title = normalized_title
            document.source_ref = source_ref
            document.file_name = file_name
            document.mime_type = mime_type
            document.file_size = size_bytes
            document.content_text = content
            document.content_hash = content_hash
            document.ingest_status = "completed"
            document.ingest_error = None
            document.chunk_count = chunk_count
            document.metadata_json = metadata_json
            document.updated_at = utc_now()
            session.add(document)

        await add_step(session, job, "split", "succeeded", {"chunkCount": chunk_count})
        await add_step(session, job, "save", "succeeded", {"documentId": document.id, "operation": operation})
        ended_at = utc_now()
        job.status = "completed"
        job.ended_at = ended_at
        job.updated_at = ended_at
        job.result_json = {
            "documentId": document.id,
            "createdDocuments": 1 if operation == "created" else 0,
            "updatedDocuments": 1 if operation == "updated" else 0,
            "unchangedDocuments": 1 if operation == "unchanged" else 0,
            "chunkCount": chunk_count,
            "documentEffects": [
                {
                    "documentId": document.id,
                    "operation": operation,
                    "documentVersion": document.version,
                    "beforeContentHash": before_hash,
                    "afterContentHash": document.content_hash,
                }
            ],
        }
        kb.updated_at = ended_at
        session.add(job)
        session.add(kb)
        await session.commit()
        return job.id


async def fetch_job_item(job_id: str) -> Dict[str, Any]:
    async with AsyncSessionLocal() as session:
        return await get_job(session, job_id)


async def delete_base(session: AsyncSession, kb_id: str) -> Dict[str, Any]:
    kb = await get_kb(session, kb_id, include_archived=True)
    document_count = await session.scalar(
        select(func.count()).select_from(KnowledgeDocument).where(KnowledgeDocument.kb_id == kb.id)
    )
    chunk_count = await session.scalar(
        select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.kb_id == kb.id)
    )
    job_count = await session.scalar(
        select(func.count()).select_from(KnowledgeIngestJob).where(KnowledgeIngestJob.kb_id == kb.id)
    )
    step_count = await session.scalar(
        select(func.count())
        .select_from(KnowledgeIngestStep)
        .where(
            KnowledgeIngestStep.job_id.in_(
                select(KnowledgeIngestJob.id).where(KnowledgeIngestJob.kb_id == kb.id)
            )
        )
    )

    await session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.kb_id == kb.id))
    await session.execute(delete(KnowledgeDocument).where(KnowledgeDocument.kb_id == kb.id))
    await session.execute(
        delete(KnowledgeIngestStep).where(
            KnowledgeIngestStep.job_id.in_(select(KnowledgeIngestJob.id).where(KnowledgeIngestJob.kb_id == kb.id))
        )
    )
    await session.execute(delete(KnowledgeIngestJob).where(KnowledgeIngestJob.kb_id == kb.id))
    await session.delete(kb)
    await session.commit()
    return {
        "kbId": kb_id,
        "deleted": True,
        "documentCount": int(document_count or 0),
        "chunkCount": int(chunk_count or 0),
        "jobCount": int(job_count or 0),
        "stepCount": int(step_count or 0),
    }


def _paginate_query(page: int | None, page_size: int | None, default_page_size: int = 20) -> tuple[int | None, int | None]:
    if page is None and page_size is None:
        return None, None
    current_page = max(1, int(page or 1))
    current_page_size = max(1, min(int(page_size or default_page_size), 100))
    return current_page, current_page_size


async def list_bases(
    session: AsyncSession,
    include_archived: bool = False,
    keyword: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
) -> Dict[str, Any]:
    conditions = []
    if not include_archived:
        conditions.append(KnowledgeBase.status == "active")
    if keyword:
        term = f"%{keyword.strip()}%"
        conditions.append(
            or_(
                KnowledgeBase.name.ilike(term),
                KnowledgeBase.namespace.ilike(term),
                KnowledgeBase.description.ilike(term),
            )
        )

    total = int(
        (await session.scalar(select(func.count()).select_from(KnowledgeBase).where(*conditions))) or 0
    )
    current_page, current_page_size = _paginate_query(page, page_size)
    if current_page is None or current_page_size is None:
        rows = (
            (await session.execute(select(KnowledgeBase).where(*conditions).order_by(KnowledgeBase.namespace, KnowledgeBase.name)))
            .scalars()
            .all()
        )
        current_page = 1
        current_page_size = len(rows) or 1
        total_pages = 1 if total else 0
    else:
        total_pages = ceil(total / current_page_size) if total else 0
        if total_pages:
            current_page = min(current_page, total_pages)
        offset = (current_page - 1) * current_page_size
        rows = (
            (
                await session.execute(
                    select(KnowledgeBase)
                    .where(*conditions)
                    .order_by(KnowledgeBase.namespace, KnowledgeBase.name)
                    .offset(offset)
                    .limit(current_page_size)
                )
            )
            .scalars()
            .all()
        )

    kb_ids = [row.id for row in rows]
    document_counts: Dict[str, int] = {}
    chunk_counts: Dict[str, int] = {}
    failed_job_counts: Dict[str, int] = {}
    if kb_ids:
        document_counts = {
            kb_id: int(count or 0)
            for kb_id, count in (
                await session.execute(
                    select(KnowledgeDocument.kb_id, func.count())
                    .where(
                        KnowledgeDocument.kb_id.in_(kb_ids),
                        KnowledgeDocument.ingest_status != "archived",
                    )
                    .group_by(KnowledgeDocument.kb_id)
                )
            ).all()
        }
        chunk_counts = {
            kb_id: int(count or 0)
            for kb_id, count in (
                await session.execute(
                    select(KnowledgeChunk.kb_id, func.count())
                    .where(
                        KnowledgeChunk.kb_id.in_(kb_ids),
                        KnowledgeChunk.status == "active",
                    )
                    .group_by(KnowledgeChunk.kb_id)
                )
            ).all()
        }
        failed_job_counts = {
            kb_id: int(count or 0)
            for kb_id, count in (
                await session.execute(
                    select(KnowledgeIngestJob.kb_id, func.count())
                    .where(
                        KnowledgeIngestJob.kb_id.in_(kb_ids),
                        KnowledgeIngestJob.status == "failed",
                    )
                    .group_by(KnowledgeIngestJob.kb_id)
                )
            ).all()
        }

    items = [
        kb_item(
            kb,
            document_counts.get(kb.id, 0),
            chunk_counts.get(kb.id, 0),
            failed_job_counts.get(kb.id, 0),
        )
        for kb in rows
    ]
    return {
        "items": items,
        "total": total,
        "page": current_page,
        "pageSize": current_page_size,
        "totalPages": total_pages,
    }


async def create_base(session: AsyncSession, payload: Dict[str, Any], actor: str) -> Dict[str, Any]:
    namespace = normalize_namespace(payload.get("namespace"))
    name = str(payload.get("name") or "").strip()
    if not name:
        raise problem(status.HTTP_400_BAD_REQUEST, "INVALID_NAME", "name is required")

    existing = await session.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.namespace == namespace,
            func.lower(KnowledgeBase.name) == name.lower(),
            KnowledgeBase.status == "active",
        )
    )
    if existing:
        raise problem(status.HTTP_409_CONFLICT, "KB_NAME_EXISTS", "active knowledge base name already exists")

    kb = KnowledgeBase(
        namespace=namespace,
        name=name[:255],
        description=payload.get("description"),
        search_policy_json=payload.get("searchPolicyJson") or {},
        metadata_extraction_json=normalize_metadata_extraction_config(payload.get("metadataExtractionJson")),
        created_by=actor,
    )
    session.add(kb)
    await session.commit()
    await session.refresh(kb)
    return kb_item(kb)


async def update_base(session: AsyncSession, kb_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    kb = await get_kb(session, kb_id, include_archived=True)
    if "namespace" in payload:
        kb.namespace = normalize_namespace(payload.get("namespace"))
    if "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise problem(status.HTTP_400_BAD_REQUEST, "INVALID_NAME", "name is required")
        exists = await session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.namespace == kb.namespace,
                func.lower(KnowledgeBase.name) == name.lower(),
                KnowledgeBase.status == "active",
                KnowledgeBase.id != kb.id,
            )
        )
        if exists:
            raise problem(status.HTTP_409_CONFLICT, "KB_NAME_EXISTS", "active knowledge base name already exists")
        kb.name = name[:255]
    if "description" in payload:
        kb.description = payload.get("description")
    if "searchPolicyJson" in payload:
        policy = payload.get("searchPolicyJson")
        if not isinstance(policy, dict):
            raise problem(status.HTTP_400_BAD_REQUEST, "INVALID_POLICY", "searchPolicyJson must be object")
        kb.search_policy_json = policy
    if "metadataExtractionJson" in payload:
        kb.metadata_extraction_json = normalize_metadata_extraction_config(payload.get("metadataExtractionJson"))
    kb.updated_at = utc_now()
    session.add(kb)
    await session.commit()
    await session.refresh(kb)
    return kb_item(kb)


async def archive_base(session: AsyncSession, kb_id: str, archived: bool) -> Dict[str, Any]:
    kb = await get_kb(session, kb_id, include_archived=True)
    kb.status = "archived" if archived else "active"
    kb.updated_at = utc_now()
    session.add(kb)
    await session.commit()
    await session.refresh(kb)
    return kb_item(kb)


async def list_documents(
    session: AsyncSession,
    kb_id: str,
    include_archived: bool = False,
    keyword: str | None = None,
    source_type: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
) -> Dict[str, Any]:
    await get_kb(session, kb_id, include_archived=True)
    conditions = [KnowledgeDocument.kb_id == kb_id]
    if not include_archived:
        conditions.append(KnowledgeDocument.ingest_status != "archived")
    if source_type and source_type != "all":
        conditions.append(KnowledgeDocument.source_type == source_type)
    if keyword:
        term = f"%{keyword.strip()}%"
        conditions.append(
            or_(
                KnowledgeDocument.title.ilike(term),
                KnowledgeDocument.source_ref.ilike(term),
                KnowledgeDocument.file_name.ilike(term),
                KnowledgeDocument.id.ilike(term),
            )
        )
    total = int(
        (await session.scalar(select(func.count()).select_from(KnowledgeDocument).where(*conditions))) or 0
    )
    current_page, current_page_size = _paginate_query(page, page_size, default_page_size=20)
    if current_page is None or current_page_size is None:
        rows = (
            (
                await session.execute(
                    select(KnowledgeDocument).where(*conditions).order_by(KnowledgeDocument.updated_at.desc())
                )
            )
            .scalars()
            .all()
        )
        current_page = 1
        current_page_size = len(rows) or 1
        total_pages = 1 if total else 0
    else:
        total_pages = ceil(total / current_page_size) if total else 0
        if total_pages:
            current_page = min(current_page, total_pages)
        offset = (current_page - 1) * current_page_size
        rows = (
            (
                await session.execute(
                    select(KnowledgeDocument)
                    .where(*conditions)
                    .order_by(KnowledgeDocument.updated_at.desc())
                    .offset(offset)
                    .limit(current_page_size)
                )
            )
            .scalars()
            .all()
        )
    return {
        "items": [document_item(row) for row in rows],
        "total": total,
        "page": current_page,
        "pageSize": current_page_size,
        "totalPages": total_pages,
    }


async def get_document(session: AsyncSession, kb_id: str, document_id: str) -> Dict[str, Any]:
    await get_kb(session, kb_id, include_archived=True)
    document = await session.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.kb_id == kb_id,
        )
    )
    if not document:
        raise problem(status.HTTP_404_NOT_FOUND, "DOCUMENT_NOT_FOUND", "knowledge document not found")
    return document_item(document)


async def archive_document(session: AsyncSession, kb_id: str, document_id: str) -> Dict[str, Any]:
    document = await session.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.kb_id == kb_id,
        )
    )
    if not document:
        raise problem(status.HTTP_404_NOT_FOUND, "DOCUMENT_NOT_FOUND", "knowledge document not found")
    document.ingest_status = "archived"
    document.updated_at = utc_now()
    await session.execute(
        delete(KnowledgeChunk).where(
            KnowledgeChunk.document_id == document_id,
            KnowledgeChunk.kb_id == kb_id,
        )
    )
    await session.commit()
    return document_item(document)


async def ingest_file(
    kb_id: str,
    *,
    file_name: str,
    mime_type: str | None,
    body: bytes,
    title: str | None,
    source_ref: str | None,
    metadata: str | Dict[str, Any] | None,
    actor: str,
    trace_id: str | None,
) -> Dict[str, Any]:
    if not body:
        raise problem(status.HTTP_400_BAD_REQUEST, "EMPTY_FILE", "file must not be empty")
    if len(body) > settings.max_file_bytes:
        raise problem(status.HTTP_400_BAD_REQUEST, "FILE_TOO_LARGE", "file exceeds size limit")

    blob_hash = sha256_bytes(body)
    file_source_hash = source_hash(blob_hash, source_ref)
    job_id = ""
    failed_step_name = "validate"

    try:
        resolved_kb_id, job_id, kb_namespace, metadata_extraction_config = await create_ingest_job(
            kb_id,
            file_name=file_name,
            mime_type=mime_type,
            size_bytes=len(body),
            title=title,
            source_ref=source_ref,
            file_source_hash=file_source_hash,
            actor=actor,
            trace_id=trace_id,
        )
        failed_step_name = "parse"
        extracted = await asyncio.to_thread(
            extract_text_from_bytes,
            file_name,
            mime_type,
            body,
            metadata_extraction_config,
        )
        content = str(extracted.get("contentText") or "").strip()
        if not content:
            raise problem(status.HTTP_400_BAD_REQUEST, "EMPTY_DOCUMENT", "document has no extractable text")
        await record_job_step(
            job_id,
            "parse",
            "succeeded",
            {"characters": len(content), "pages": extracted.get("pages")},
        )

        normalized_title = (title or str(extracted.get("title") or file_name)).strip()[:512] or file_name
        metadata_json = normalize_metadata(
            metadata,
            extracted_metadata=extracted.get("metadata"),
            file_name=file_name,
            extraction_config=metadata_extraction_config,
            ingest_fields={
                "blobSha256": blob_hash,
                "source": "upload",
                "metadataSource": extracted.get("metadataSource"),
            },
        )
        content_hash = sha256_text(f"{normalized_title}\n{content}")
        failed_step_name = "split"
        document_state = await get_existing_document_state(resolved_kb_id, file_source_hash)
        chunks: List[str] = []
        embeddings: List[List[float]] = []
        if not (
            document_state
            and document_state["contentHash"] == content_hash
            and document_state["ingestStatus"] == "completed"
        ):
            chunks = chunk_text(normalized_title, content)
            if not chunks:
                raise problem(status.HTTP_400_BAD_REQUEST, "EMPTY_DOCUMENT", "document has no extractable text")
            failed_step_name = "embed"
            embeddings = await get_embeddings(chunks)

        failed_step_name = "save"
        await complete_ingest_job(
            resolved_kb_id,
            job_id,
            file_name=file_name,
            mime_type=mime_type,
            size_bytes=len(body),
            normalized_title=normalized_title,
            source_ref=source_ref,
            file_source_hash=file_source_hash,
            content_hash=content_hash,
            content=content,
            metadata_json=metadata_json,
            actor=actor,
            chunks=chunks,
            embeddings=embeddings,
        )
    except HTTPException as exc:
        if job_id:
            logger.exception("knowledge_ingest_rejected", error=str(exc), job_id=job_id)
            await fail_job_by_id(job_id, exc, step_name=failed_step_name)
        raise
    except Exception as exc:
        if job_id:
            logger.exception("knowledge_ingest_failed", error=str(exc), job_id=job_id)
            await fail_job_by_id(job_id, exc, step_name=failed_step_name)
        raise problem(status.HTTP_500_INTERNAL_SERVER_ERROR, "INGEST_FAILED", "failed to ingest document") from exc

    return await fetch_job_item(job_id)


async def fail_job(session: AsyncSession, job: KnowledgeIngestJob, exc: Exception, step_name: str = "save") -> None:
    ended_at = utc_now()
    message = ingest_error_message(exc)
    job.status = "failed"
    job.error_message = message[:1000]
    job.ended_at = ended_at
    job.updated_at = ended_at
    await add_step(session, job, step_name, "failed", {}, message[:1000])
    session.add(job)
    await session.commit()


async def fail_job_by_id(job_id: str, exc: Exception, step_name: str = "save") -> None:
    async with AsyncSessionLocal() as session:
        job = await session.scalar(select(KnowledgeIngestJob).where(KnowledgeIngestJob.id == job_id))
        if not job:
            logger.warning("knowledge_ingest_job_missing", job_id=job_id)
            return
        await fail_job(session, job, exc, step_name=step_name)


async def list_jobs(
    session: AsyncSession,
    kb_id: str | None = None,
    status_value: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
) -> Dict[str, Any]:
    conditions = []
    if kb_id:
        conditions.append(KnowledgeIngestJob.kb_id == kb_id)
    if status_value:
        conditions.append(KnowledgeIngestJob.status == status_value)
    total = int((await session.scalar(select(func.count()).select_from(KnowledgeIngestJob).where(*conditions))) or 0)
    current_page, current_page_size = _paginate_query(page, page_size, default_page_size=20)
    if current_page is None or current_page_size is None:
        rows = (
            (
                await session.execute(
                    select(KnowledgeIngestJob).where(*conditions).order_by(KnowledgeIngestJob.updated_at.desc())
                )
            )
            .scalars()
            .all()
        )
        current_page = 1
        current_page_size = len(rows) or 1
        total_pages = 1 if total else 0
    else:
        total_pages = ceil(total / current_page_size) if total else 0
        if total_pages:
            current_page = min(current_page, total_pages)
        offset = (current_page - 1) * current_page_size
        rows = (
            (
                await session.execute(
                    select(KnowledgeIngestJob)
                    .where(*conditions)
                    .order_by(KnowledgeIngestJob.updated_at.desc())
                    .offset(offset)
                    .limit(current_page_size)
                )
            )
            .scalars()
            .all()
        )
    return {
        "items": [job_item(row) for row in rows],
        "total": total,
        "page": current_page,
        "pageSize": current_page_size,
        "totalPages": total_pages,
    }


async def get_job(session: AsyncSession, job_id: str) -> Dict[str, Any]:
    job = await session.scalar(select(KnowledgeIngestJob).where(KnowledgeIngestJob.id == job_id))
    if not job:
        raise problem(status.HTTP_404_NOT_FOUND, "JOB_NOT_FOUND", "knowledge ingest job not found")
    steps = (
        (await session.execute(select(KnowledgeIngestStep).where(KnowledgeIngestStep.job_id == job.id)))
        .scalars()
        .all()
    )
    steps.sort(key=lambda item: item.started_at or datetime.min)
    return job_item(job, steps)


async def delete_job(session: AsyncSession, job_id: str) -> Dict[str, Any]:
    job = await session.scalar(select(KnowledgeIngestJob).where(KnowledgeIngestJob.id == job_id))
    if not job:
        raise problem(status.HTTP_404_NOT_FOUND, "JOB_NOT_FOUND", "knowledge ingest job not found")
    if job.status not in TERMINAL_JOB_STATUSES and job.status != "running":
        raise problem(status.HTTP_409_CONFLICT, "JOB_NOT_TERMINAL", "queued jobs cannot be deleted")
    await session.execute(delete(KnowledgeIngestStep).where(KnowledgeIngestStep.job_id == job_id))
    await session.delete(job)
    await session.commit()
    return {
        "jobId": job_id,
        "deletedJobCount": 1,
        "deletedDocumentCount": 0,
        "preservedDocumentCount": 0,
        "contentDeleted": False,
    }


async def clear_jobs(session: AsyncSession, kb_id: str) -> Dict[str, Any]:
    await get_kb(session, kb_id, include_archived=True)
    terminal_job_ids = list(
        (
            await session.scalars(
                select(KnowledgeIngestJob.id).where(
                    KnowledgeIngestJob.kb_id == kb_id,
                    KnowledgeIngestJob.status.in_(TERMINAL_JOB_STATUSES),
                )
            )
        ).all()
    )
    if not terminal_job_ids:
        preserved_job_count = int(
            (
                await session.scalar(
                    select(func.count()).select_from(KnowledgeIngestJob).where(
                        KnowledgeIngestJob.kb_id == kb_id,
                    )
                )
            )
            or 0
        )
        return {
            "kbId": kb_id,
            "deletedJobCount": 0,
            "preservedJobCount": preserved_job_count,
        }

    await session.execute(
        delete(KnowledgeIngestStep).where(KnowledgeIngestStep.job_id.in_(terminal_job_ids))
    )
    await session.execute(
        delete(KnowledgeIngestJob).where(KnowledgeIngestJob.id.in_(terminal_job_ids))
    )
    await session.commit()
    preserved_job_count = int(
        (
            await session.scalar(
                select(func.count()).select_from(KnowledgeIngestJob).where(
                    KnowledgeIngestJob.kb_id == kb_id,
                )
            )
        )
        or 0
    )
    return {
        "kbId": kb_id,
        "deletedJobCount": len(terminal_job_ids),
        "preservedJobCount": preserved_job_count,
    }


def metadata_matches(expected: Dict[str, Any], document_metadata: Dict[str, Any], chunk_metadata: Dict[str, Any]) -> bool:
    if not expected:
        return True
    combined = {**document_metadata, **chunk_metadata}
    if isinstance(document_metadata.get("common"), dict):
        # Keep legacy flat filters working while new callers can use nested paths.
        aliases = {
            **document_metadata.get("_raw", {}),
            **document_metadata.get("common", {}),
            **document_metadata.get("domain", {}),
        }
        aliases.update(chunk_metadata)
        combined = {**aliases, **combined}
    return metadata_subset(expected, combined)


def metadata_subset(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(key in actual and metadata_subset(value, actual[key]) for key, value in expected.items())
    return expected == actual
