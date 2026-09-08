"""
认证工具模块 - JWT Token 创建、验证和用户认证依赖项。

本模块提供了应用认证系统的核心功能：

1. Token 管理：
   - create_access_token: 创建 JWT 访问令牌。
   - verify_token: 验证和解码 JWT 令牌。

2. FastAPI 依赖项：
   - verify_session_access: 验证会话级别的访问权限。
   - get_current_user: 验证用户身份并返回 User 对象。

JWT Token 设计：
    Token 的 sub（Subject）字段承载 thread_id，
    可以是 user_id（用户级 Token）或 session_id（会话级 Token）。
    get_current_user 智能处理这两种情况：
    - 纯数字 subject → 作为 user_id 查询。
    - 非数字 subject → 作为 session_id 查询 → 获取所属用户。

认证流程：
    1. 前端在 Authorization 头中发送 Bearer Token。
    2. HTTPBearer 中间件提取 Token。
    3. verify_token 解码并验证签名和过期时间。
    4. 业务依赖项（verify_session_access / get_current_user）进行业务级鉴权。
"""

import re
from datetime import (
    UTC,
    datetime,
    timedelta,
)
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import (
    JWTError,
    jwt,
)

from app.core.config import settings
from app.core.logging import logger
from app.models.user import User
from app.schemas.auth import Token
from app.services.database import database_service
from app.utils.sanitization import sanitize_string

# HTTPBearer 安全方案实例
# 自动从请求的 Authorization 头中提取 Bearer Token
security = HTTPBearer()


# ============================================================================
# Token 创建与验证
# ============================================================================

def create_access_token(thread_id: str, expires_delta: Optional[timedelta] = None) -> Token:
    """
    创建 JWT 访问令牌。

    JWT Payload 结构：
    - sub (Subject): thread_id（用户 ID 或会话 ID）。
    - exp (Expiration): 令牌过期时间。
    - iat (Issued At): 令牌签发时间。
    - jti (JWT ID): 令牌唯一标识（用于防重放攻击，已净化处理）。

    Args:
        thread_id: 要嵌入 Token 的标识符（用户 ID 或会话 ID）。
        expires_delta: 自定义过期时间，不传则使用配置的默认值（默认 30 天）。

    Returns:
        Token: 包含 access_token、token_type 和 expires_at 的 Token 对象。
    """
    # 计算过期时间
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(days=settings.JWT_ACCESS_TOKEN_EXPIRE_DAYS)

    # 构建 JWT Payload
    to_encode = {
        "sub": str(thread_id),
        "exp": expire,
        "iat": datetime.now(UTC),
        # jti 用于唯一标识令牌（防重放），这里使用 thread_id + 时间戳组合
        "jti": sanitize_string(f"{thread_id}-{datetime.now(UTC).timestamp()}"),
    }

    # 编码 JWT
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return Token(access_token=encoded_jwt, expires_at=expire)


def verify_token(token: str) -> Optional[str]:
    """
    验证 JWT Token 并提取 subject。

    验证内容包括：
    - Token 格式是否正确。
    - 签名是否有效（使用 JWT_SECRET_KEY）。
    - Token 是否过期。

    Args:
        token: JWT Token 字符串。

    Returns:
        Optional[str]: Token 中的 sub 字段值（thread_id），验证失败返回 None。
    """
    # 基本校验：Token 不能为空且必须是字符串
    if not token or not isinstance(token, str):
        return None
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        thread_id: str = payload.get("sub")
        return thread_id
    except JWTError as e:
        logger.warning("token_validation_failed", error=str(e))
        return None


# ============================================================================
# FastAPI 认证依赖项
# ============================================================================

async def verify_session_access(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """
    验证会话访问权限 - FastAPI 依赖项。

    从请求的 Authorization 头中提取 Token，验证其有效性，
    并返回 Token 中的 session_id。

    用法：
        @router.post("/chat")
        async def chat(session_id: str = Depends(verify_session_access)):
            ...

    Args:
        credentials: HTTPBearer 从请求中提取的凭据。

    Returns:
        str: 验证通过后的 session_id。

    Raises:
        HTTPException(401): Token 无效或验证失败时抛出。
    """
    token = credentials.credentials
    session_id = verify_token(token)

    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return session_id


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    """
    获取当前认证用户 - FastAPI 依赖项。

    验证 Token 并返回对应的 User 对象。智能处理两种 Token 类型：
    1. 用户 Token（sub 为纯数字 user_id）→ 直接查询用户。
    2. 会话 Token（sub 为 session_id）→ 查 session → 获取所属用户。

    用法：
        @router.get("/profile")
        async def profile(user: User = Depends(get_current_user)):
            ...

    Args:
        credentials: HTTPBearer 从请求中提取的凭据。

    Returns:
        User: 认证通过的用户对象。

    Raises:
        HTTPException(401): Token 无效、用户不存在时抛出。
    """
    token = credentials.credentials
    subject = verify_token(token)

    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 策略 1: 尝试将 subject 作为用户 ID（纯数字）查询
    if subject.isdigit():
        user = await database_service.get_user_by_id(int(subject))
        if user:
            return user

    # 策略 2: 尝试将 subject 作为会话 ID 查询
    try:
        session = await database_service.get_session(subject)
        if session:
            user = await database_service.get_user_by_id(session.user_id)
            if user:
                return user
            else:
                # 会话存在但用户被删除（数据不一致）
                logger.error("session_found_but_user_missing", session_id=subject, user_id=session.user_id)
        else:
            # 会话不存在（可能是过期或被删除）
            logger.warning("session_not_found_in_db", session_id=subject)

    except Exception as e:
        logger.exception("auth_db_lookup_failed", error=str(e))

    # 所有查询都失败
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="User not found",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_platform_admin(user: User = Depends(get_current_user)) -> User:
    """
    要求当前用户具备平台管理员权限。

    本地开发阶段使用 PLATFORM_ADMIN_EMAILS 邮箱白名单。生产阶段可以将此处
    替换为 SSO/租户权限系统，但路由层依赖保持不变。
    """
    allowed_emails = {email.lower() for email in settings.PLATFORM_ADMIN_EMAILS}
    if user.email.lower() not in allowed_emails:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform admin access required",
        )
    return user
