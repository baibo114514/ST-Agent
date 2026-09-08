"""
独立 Knowledge Service 入口。

该服务只暴露内部 API 给主后端调用；浏览器端不应直接访问这里。主后端负责
平台管理员鉴权、JWT 校验和前端契约，knowledge-service 负责知识库、文档、
分片、向量索引和检索。
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, FastAPI, File, Form, Header, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limiter import limiter
from app.core.logging import logger
from services.knowledge_service.config import settings
from services.knowledge_service.db import init_database, session_dependency
from services.knowledge_service.retrieval import search
from services.knowledge_service.security import actor_from_headers, require_service_token
from services.knowledge_service.service import (
    archive_base,
    archive_document,
    clear_jobs,
    close_rerank_client,
    create_base,
    delete_base,
    delete_job,
    get_base,
    get_document,
    get_embedding,
    get_job,
    ingest_file,
    list_bases,
    list_documents,
    list_jobs,
    update_base,
)


READ_LIMIT = "120 per minute"
WRITE_LIMIT = "60 per minute"
INGEST_LIMIT = settings.ingest_rate_limit
SEARCH_LIMIT = "60 per minute"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("knowledge_service_startup", service_name=settings.service_name)
    app.state.ingest_semaphore = asyncio.Semaphore(settings.ingest_concurrency)
    await init_database()
    logger.info("knowledge_service_database_ready")
    # 预热 embedding 模型（触发 Ollama 加载 bge-m3），避免首次检索冷启动
    try:
        await get_embedding("预热")
        logger.info("knowledge_service_embedding_warmed_up")
    except Exception as exc:
        logger.warning("knowledge_service_embedding_warmup_failed", error=str(exc))
    yield
    await close_rerank_client()
    logger.info("knowledge_service_shutdown", service_name=settings.service_name)


app = FastAPI(
    title="Knowledge Service",
    version="1.0.0",
    description="Independent document knowledge-base service for FastGraph Agent Engine.",
    openapi_url="/internal/v1/kb/openapi.json",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

router = APIRouter(
    prefix="/internal/v1/kb",
    dependencies=[Depends(require_service_token)],
)


@app.get("/health")
@limiter.limit(READ_LIMIT)
async def public_health(request: Request, session: AsyncSession = Depends(session_dependency)):
    await session.scalar(text("SELECT 1"))
    return {"status": "healthy", "service": settings.service_name}


@router.get("/health")
@limiter.limit(READ_LIMIT)
async def internal_health(request: Request, session: AsyncSession = Depends(session_dependency)):
    await session.scalar(text("SELECT 1"))
    return {"status": "healthy", "service": settings.service_name}


@router.get("/bases")
@limiter.limit(READ_LIMIT)
async def route_list_bases(
    request: Request,
    include_archived: bool = Query(False, alias="includeArchived"),
    keyword: str | None = Query(None),
    page: int | None = Query(None),
    page_size: int | None = Query(None, alias="pageSize"),
    session: AsyncSession = Depends(session_dependency),
):
    return await list_bases(
        session,
        include_archived=include_archived,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )


@router.get("/bases/{kb_id}")
@limiter.limit(READ_LIMIT)
async def route_get_base(
    request: Request,
    kb_id: str,
    session: AsyncSession = Depends(session_dependency),
):
    return await get_base(session, kb_id, include_archived=True)


@router.post("/bases")
@limiter.limit(WRITE_LIMIT)
async def route_create_base(
    request: Request,
    payload: Dict[str, Any] = Body(...),
    actor: str = Depends(actor_from_headers),
    session: AsyncSession = Depends(session_dependency),
):
    return await create_base(session, payload, actor)


@router.put("/bases/{kb_id}")
@limiter.limit(WRITE_LIMIT)
async def route_update_base(
    request: Request,
    kb_id: str,
    payload: Dict[str, Any] = Body(...),
    session: AsyncSession = Depends(session_dependency),
):
    return await update_base(session, kb_id, payload)


@router.delete("/bases/{kb_id}")
@limiter.limit(WRITE_LIMIT)
async def route_delete_base(
    request: Request,
    kb_id: str,
    session: AsyncSession = Depends(session_dependency),
):
    return await delete_base(session, kb_id)


@router.post("/bases/{kb_id}/archive")
@limiter.limit(WRITE_LIMIT)
async def route_archive_base(
    request: Request,
    kb_id: str,
    session: AsyncSession = Depends(session_dependency),
):
    return await archive_base(session, kb_id, archived=True)


@router.post("/bases/{kb_id}/restore")
@limiter.limit(WRITE_LIMIT)
async def route_restore_base(
    request: Request,
    kb_id: str,
    session: AsyncSession = Depends(session_dependency),
):
    return await archive_base(session, kb_id, archived=False)


@router.get("/bases/{kb_id}/documents")
@limiter.limit(READ_LIMIT)
async def route_list_documents(
    request: Request,
    kb_id: str,
    include_archived: bool = Query(False, alias="includeArchived"),
    keyword: str | None = Query(None),
    source_type: str | None = Query(None, alias="sourceType"),
    page: int | None = Query(None),
    page_size: int | None = Query(None, alias="pageSize"),
    session: AsyncSession = Depends(session_dependency),
):
    return await list_documents(
        session,
        kb_id,
        include_archived=include_archived,
        keyword=keyword,
        source_type=source_type,
        page=page,
        page_size=page_size,
    )


@router.get("/bases/{kb_id}/documents/{document_id}")
@limiter.limit(READ_LIMIT)
async def route_get_document(
    request: Request,
    kb_id: str,
    document_id: str,
    session: AsyncSession = Depends(session_dependency),
):
    return await get_document(session, kb_id, document_id)


@router.post("/bases/{kb_id}/documents/{document_id}/archive")
@limiter.limit(WRITE_LIMIT)
async def route_archive_document(
    request: Request,
    kb_id: str,
    document_id: str,
    session: AsyncSession = Depends(session_dependency),
):
    return await archive_document(session, kb_id, document_id)


@router.post("/bases/{kb_id}/ingest/file")
@limiter.limit(INGEST_LIMIT)
async def route_ingest_file(
    request: Request,
    kb_id: str,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    source_ref: str | None = Form(None, alias="sourceRef"),
    metadata: str | None = Form(None),
    actor: str = Depends(actor_from_headers),
    x_trace_id: str | None = Header(None),
):
    body = await file.read()
    async with request.app.state.ingest_semaphore:
        return await ingest_file(
            kb_id,
            file_name=file.filename or "upload",
            mime_type=file.content_type,
            body=body,
            title=title,
            source_ref=source_ref,
            metadata=metadata,
            actor=actor,
            trace_id=x_trace_id,
        )


@router.get("/jobs")
@limiter.limit(READ_LIMIT)
async def route_list_jobs(
    request: Request,
    kb_id: str | None = Query(None, alias="kbId"),
    status_value: str | None = Query(None, alias="status"),
    page: int | None = Query(None),
    page_size: int | None = Query(None, alias="pageSize"),
    session: AsyncSession = Depends(session_dependency),
):
    return await list_jobs(
        session,
        kb_id=kb_id,
        status_value=status_value,
        page=page,
        page_size=page_size,
    )


@router.get("/jobs/{job_id}")
@limiter.limit(READ_LIMIT)
async def route_get_job(
    request: Request,
    job_id: str,
    session: AsyncSession = Depends(session_dependency),
):
    return await get_job(session, job_id)


@router.delete("/jobs")
@limiter.limit(WRITE_LIMIT)
async def route_clear_jobs(
    request: Request,
    kb_id: str = Query(..., alias="kbId"),
    session: AsyncSession = Depends(session_dependency),
):
    return await clear_jobs(session, kb_id)


@router.delete("/jobs/{job_id}")
@limiter.limit(WRITE_LIMIT)
async def route_delete_job(
    request: Request,
    job_id: str,
    session: AsyncSession = Depends(session_dependency),
):
    return await delete_job(session, job_id)


@router.post("/search")
@limiter.limit(SEARCH_LIMIT)
async def route_search(
    request: Request,
    payload: Dict[str, Any] = Body(...),
    session: AsyncSession = Depends(session_dependency),
):
    return await search(session, payload)


app.include_router(router)
