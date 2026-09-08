"""
平台管理员 API。

该模块对应三层架构中的 control-plane 管理接口：
- 平台 Agent Catalog：创建、编辑、发布、下线 Agent。
- Knowledge proxy：代理独立 knowledge-service 的知识库管理、上传和检索。
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, File, Form, Query, Request, UploadFile

from app.core.config import settings
from app.core.limiter import limiter
from app.models.user import User
from app.schemas.agent import (
    PlatformAgentPage,
    PlatformAgentStatusUpdate,
    PlatformAgentWrite,
)
from app.services.agent_config import agent_config_service
from app.services.knowledge_client import knowledge_service_client
from app.utils.auth import require_platform_admin


router = APIRouter()


@router.get("/agent-catalog", response_model=PlatformAgentPage)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["platform_admin"][0])
async def list_platform_agents(
    request: Request,
    include_offline: bool = Query(True, alias="includeOffline"),
    user: User = Depends(require_platform_admin),
):
    items = await agent_config_service.list_platform_agents(include_offline=include_offline)
    return PlatformAgentPage(items=items, total=len(items))


@router.post("/agent-catalog", response_model_exclude_none=True)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["platform_admin"][0])
async def create_platform_agent(
    request: Request,
    payload: PlatformAgentWrite = Body(...),
    user: User = Depends(require_platform_admin),
):
    return await agent_config_service.create_platform_agent(payload, user)


@router.put("/agent-catalog/{agent_id}", response_model_exclude_none=True)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["platform_admin"][0])
async def update_platform_agent(
    request: Request,
    agent_id: str,
    payload: PlatformAgentWrite = Body(...),
    user: User = Depends(require_platform_admin),
):
    return await agent_config_service.update_platform_agent(agent_id, payload, user)


@router.put("/agent-catalog/{agent_id}/status", response_model_exclude_none=True)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["platform_admin"][0])
async def change_platform_agent_status(
    request: Request,
    agent_id: str,
    payload: PlatformAgentStatusUpdate = Body(...),
    user: User = Depends(require_platform_admin),
):
    return await agent_config_service.change_status(agent_id, payload.status, user)


@router.get("/knowledge-health")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["knowledge_proxy"][0])
async def knowledge_health(
    request: Request,
    user: User = Depends(require_platform_admin),
):
    return await knowledge_service_client.get("/internal/v1/kb/health", actor=user)


@router.get("/knowledge-bases")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["knowledge_proxy"][0])
async def list_knowledge_bases(
    request: Request,
    include_archived: bool = Query(False, alias="includeArchived"),
    keyword: Optional[str] = Query(None),
    page: Optional[int] = Query(None),
    page_size: Optional[int] = Query(None, alias="pageSize"),
    user: User = Depends(require_platform_admin),
):
    return await knowledge_service_client.get(
        "/internal/v1/kb/bases",
        actor=user,
        params={
            "includeArchived": include_archived,
            "keyword": keyword,
            "page": page,
            "pageSize": page_size,
        },
    )


@router.get("/knowledge-bases/{kb_id}")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["knowledge_proxy"][0])
async def get_knowledge_base(
    request: Request,
    kb_id: str,
    user: User = Depends(require_platform_admin),
):
    return await knowledge_service_client.get(f"/internal/v1/kb/bases/{kb_id}", actor=user)


@router.post("/knowledge-bases")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["knowledge_proxy"][0])
async def create_knowledge_base(
    request: Request,
    payload: Dict[str, Any] = Body(...),
    user: User = Depends(require_platform_admin),
):
    return await knowledge_service_client.post_json("/internal/v1/kb/bases", payload, actor=user)


@router.put("/knowledge-bases/{kb_id}")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["knowledge_proxy"][0])
async def update_knowledge_base(
    request: Request,
    kb_id: str,
    payload: Dict[str, Any] = Body(...),
    user: User = Depends(require_platform_admin),
):
    return await knowledge_service_client.put_json(f"/internal/v1/kb/bases/{kb_id}", payload, actor=user)


@router.delete("/knowledge-bases/{kb_id}")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["knowledge_proxy"][0])
async def delete_knowledge_base(
    request: Request,
    kb_id: str,
    user: User = Depends(require_platform_admin),
):
    result = await knowledge_service_client.delete(f"/internal/v1/kb/bases/{kb_id}", actor=user)
    unlinked_agent_count = await agent_config_service.unlink_knowledge_base(kb_id, user)
    if isinstance(result, dict):
        result["unlinkedAgentCount"] = unlinked_agent_count
    return result


@router.post("/knowledge-bases/{kb_id}/archive")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["knowledge_proxy"][0])
async def archive_knowledge_base(
    request: Request,
    kb_id: str,
    user: User = Depends(require_platform_admin),
):
    return await knowledge_service_client.post_empty(f"/internal/v1/kb/bases/{kb_id}/archive", actor=user)


@router.post("/knowledge-bases/{kb_id}/restore")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["knowledge_proxy"][0])
async def restore_knowledge_base(
    request: Request,
    kb_id: str,
    user: User = Depends(require_platform_admin),
):
    return await knowledge_service_client.post_empty(f"/internal/v1/kb/bases/{kb_id}/restore", actor=user)


@router.get("/knowledge-bases/{kb_id}/documents")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["knowledge_proxy"][0])
async def list_knowledge_documents(
    request: Request,
    kb_id: str,
    include_archived: bool = Query(False, alias="includeArchived"),
    keyword: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None, alias="sourceType"),
    page: Optional[int] = Query(None),
    page_size: Optional[int] = Query(None, alias="pageSize"),
    user: User = Depends(require_platform_admin),
):
    return await knowledge_service_client.get(
        f"/internal/v1/kb/bases/{kb_id}/documents",
        actor=user,
        params={
            "includeArchived": include_archived,
            "keyword": keyword,
            "sourceType": source_type,
            "page": page,
            "pageSize": page_size,
        },
    )


@router.get("/knowledge-bases/{kb_id}/documents/{document_id}")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["knowledge_proxy"][0])
async def get_knowledge_document(
    request: Request,
    kb_id: str,
    document_id: str,
    user: User = Depends(require_platform_admin),
):
    return await knowledge_service_client.get(
        f"/internal/v1/kb/bases/{kb_id}/documents/{document_id}",
        actor=user,
    )


@router.post("/knowledge-bases/{kb_id}/documents/{document_id}/archive")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["knowledge_proxy"][0])
async def archive_knowledge_document(
    request: Request,
    kb_id: str,
    document_id: str,
    user: User = Depends(require_platform_admin),
):
    return await knowledge_service_client.post_empty(
        f"/internal/v1/kb/bases/{kb_id}/documents/{document_id}/archive",
        actor=user,
    )


@router.post("/knowledge-bases/{kb_id}/ingest/file")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["knowledge_ingest"][0])
async def ingest_knowledge_file(
    request: Request,
    kb_id: str,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    source_ref: Optional[str] = Form(None, alias="sourceRef"),
    metadata: Optional[str] = Form(None),
    user: User = Depends(require_platform_admin),
):
    body = await file.read()
    return await knowledge_service_client.post_multipart(
        f"/internal/v1/kb/bases/{kb_id}/ingest/file",
        actor=user,
        file_name=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
        body=body,
        fields={
            "title": title,
            "sourceRef": source_ref,
            "metadata": metadata,
        },
    )


@router.get("/knowledge-ingest-jobs")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["knowledge_proxy"][0])
async def list_knowledge_jobs(
    request: Request,
    kb_id: Optional[str] = Query(None, alias="kbId"),
    status_value: Optional[str] = Query(None, alias="status"),
    page: Optional[int] = Query(None),
    page_size: Optional[int] = Query(None, alias="pageSize"),
    user: User = Depends(require_platform_admin),
):
    return await knowledge_service_client.get(
        "/internal/v1/kb/jobs",
        actor=user,
        params={
            "kbId": kb_id,
            "status": status_value,
            "page": page,
            "pageSize": page_size,
        },
    )


@router.get("/knowledge-ingest-jobs/{job_id}")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["knowledge_proxy"][0])
async def get_knowledge_job(
    request: Request,
    job_id: str,
    user: User = Depends(require_platform_admin),
):
    return await knowledge_service_client.get(f"/internal/v1/kb/jobs/{job_id}", actor=user)


@router.delete("/knowledge-ingest-jobs")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["knowledge_proxy"][0])
async def clear_knowledge_jobs(
    request: Request,
    kb_id: str = Query(..., alias="kbId"),
    user: User = Depends(require_platform_admin),
):
    return await knowledge_service_client.delete(
        "/internal/v1/kb/jobs",
        actor=user,
        params={"kbId": kb_id},
    )


@router.delete("/knowledge-ingest-jobs/{job_id}")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["knowledge_proxy"][0])
async def delete_knowledge_job(
    request: Request,
    job_id: str,
    user: User = Depends(require_platform_admin),
):
    return await knowledge_service_client.delete(f"/internal/v1/kb/jobs/{job_id}", actor=user)


@router.post("/knowledge-search")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["knowledge_proxy"][0])
async def search_knowledge(
    request: Request,
    payload: Dict[str, Any] = Body(...),
    user: User = Depends(require_platform_admin),
):
    return await knowledge_service_client.post_json("/internal/v1/kb/search", payload, actor=user)
