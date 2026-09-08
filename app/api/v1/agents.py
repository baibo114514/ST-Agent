"""
普通用户 Agent API。

普通用户只调用平台已发布 Agent。Agent 配置由平台管理员维护，用户请求进入
LangGraph 前会按配置完成知识库预检索和上下文注入。
"""

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.core.langgraph.graph import chatbot
from app.core.limiter import limiter
from app.core.logging import logger
from app.models.user import User
from app.schemas.agent import PublicAgentPage
from app.schemas.chat import ChatRequest
from app.services.agent_config import agent_config_service
from app.utils.auth import get_current_user, verify_session_access


router = APIRouter()


@router.get("", response_model=PublicAgentPage)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["agent_catalog"][0])
async def list_agents(request: Request, user: User = Depends(get_current_user)):
    items = await agent_config_service.list_public_agents()
    return PublicAgentPage(items=items, total=len(items))


@router.post("/{agent_id}/chat/stream")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["agent_chat_stream"][0])
async def agent_chat_stream(
    request: Request,
    agent_id: str,
    payload: ChatRequest = Body(...),
    session_id: str = Depends(verify_session_access),
    user: User = Depends(get_current_user),
):
    runtime = await agent_config_service.prepare_runtime_messages(agent_id, payload.messages, user)

    async def event_generator():
        try:
            async for chunk in chatbot.astream_response(
                session_id=session_id,
                messages=runtime["messages"],
                features=runtime["features"],
                user_id=str(user.id),
                agent_instructions=runtime["agent_instructions"],
                model_name=runtime["model_name"],
                agent_code=runtime["agent_code"],
                knowledge=runtime["knowledge"],
            ):
                yield chunk
        except Exception as exc:
            logger.exception("agent_chat_stream_error", error=str(exc), agent_id=agent_id)
            yield f"\n[Error: {str(exc)}]"

    return StreamingResponse(event_generator(), media_type="text/plain")
