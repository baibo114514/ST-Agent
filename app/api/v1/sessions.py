"""
会话管理 API。

本模块统一管理「会话」相关的所有端点，是旧 chatbot.py（对话/历史/恢复）与
auth.py（会话 CRUD）的整合：

- POST   /sessions                      创建会话（同时创建 LangGraph Thread）
- GET    /sessions                      列出当前用户的会话
- DELETE /sessions/{session_id}         删除会话（需归属校验）
- GET    /sessions/{session_id}/history 读取会话聊天记录
- DELETE /sessions/{session_id}/history 清空会话聊天记录
- POST   /sessions/{session_id}/resume  恢复被中断的会话（邮件审批）

鉴权：统一使用 get_current_user（同时兼容用户 token 与会话 token），
历史/恢复等按 session_id 定位的资源额外做归属校验，防止越权访问。
"""

import uuid
from typing import List

from fastapi import APIRouter, Body, Depends, HTTPException, status

from app.core.langgraph.graph import chatbot
from app.core.logging import logger
from app.models.user import User
from app.schemas.auth import SessionResponse
from app.schemas.chat import Message, ResumeRequest
from app.services.database import database_service
from app.utils.auth import create_access_token, get_current_user
from app.utils.sanitization import sanitize_string


router = APIRouter()


async def _get_owned_session(session_id: str, user: User):
    """校验会话存在且属于当前用户，否则抛 404（防止越权读/清/恢复）。"""
    session = await database_service.get_session(session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


@router.post("", response_model=SessionResponse)
async def create_session(
    name: str = "New Chat",
    user: User = Depends(get_current_user),
):
    """创建新的聊天会话，并签发会话专属 JWT Token。"""
    try:
        session_id = str(uuid.uuid4())
        sanitized_name = sanitize_string(name) or "New Chat"
        session = await database_service.create_session(
            user_id=user.id,
            name=sanitized_name,
            session_id=session_id,
        )
        token = create_access_token(thread_id=session_id)
        return SessionResponse(session_id=session.id, name=session.name, token=token)
    except Exception as e:
        logger.exception("create_session_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to create session")


@router.get("", response_model=List[SessionResponse])
async def get_user_sessions(user: User = Depends(get_current_user)):
    """获取当前用户的所有会话，按创建时间倒序。"""
    try:
        sessions = await database_service.get_user_sessions(user.id)
        return [
            SessionResponse(
                session_id=s.id,
                name=s.name,
                token=create_access_token(s.id),
            )
            for s in sessions
        ]
    except Exception as e:
        logger.exception("get_sessions_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to retrieve sessions")


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    user: User = Depends(get_current_user),
):
    """删除指定会话（需归属校验）。"""
    await _get_owned_session(session_id, user)
    await database_service.delete_session(session_id)


@router.get("/{session_id}/history", response_model=List[Message])
async def get_history(
    session_id: str,
    user: User = Depends(get_current_user),
):
    """读取会话聊天记录（按 session_id，与具体 Agent 无关）。"""
    await _get_owned_session(session_id, user)
    return await chatbot.get_chat_history(session_id)


@router.delete("/{session_id}/history")
async def clear_history(
    session_id: str,
    user: User = Depends(get_current_user),
):
    """清空会话聊天记录（删除 LangGraph 检查点数据，不可恢复）。"""
    await _get_owned_session(session_id, user)
    await chatbot.clear_chat_history(session_id)
    return {"message": "History cleared"}


@router.post("/{session_id}/resume")
async def resume_chat(
    session_id: str,
    request: ResumeRequest = Body(...),
    user: User = Depends(get_current_user),
):
    """恢复被中断的会话执行（如邮件审批后的批准/拒绝）。"""
    await _get_owned_session(session_id, user)
    result = await chatbot.resume_graph(session_id, request.approved)
    return {"message": result}
