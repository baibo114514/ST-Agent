"""
认证相关的 API 路由模块。

本模块定义了用户认证相关的 REST API 端点：
- POST /register : 用户注册（创建账号并返回 Token）。
- POST /login    : 用户登录（验证邮箱密码并返回 Token）。
- GET  /me       : 获取当前用户信息。

（会话管理端点已迁移至 app/api/v1/sessions.py。）

安全设计：
1. 密码使用 bcrypt 哈希存储，不保存明文。
2. 注册和登录返回 JWT Token，包含 user_id。
3. 登录失败不区分"邮箱不存在"和"密码错误"，防止用户枚举攻击。
"""

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from fastapi.security import OAuth2PasswordRequestForm

from app.core.config import settings
from app.models.user import User
from app.schemas.auth import (
    MeResponse,
    TokenResponse,
    UserCreate,
    UserResponse,
)
from app.services.database import database_service
from app.utils.auth import (
    create_access_token,
    get_current_user,  # 直接导入修复好的认证依赖项
)

# 创建路由器实例
# 该路由器在 api.py 中被挂载到 /auth 路径下
router = APIRouter()


def _is_platform_admin(user: User) -> bool:
    """判断用户是否为平台管理员（基于邮箱白名单）。"""
    allowed = {email.lower() for email in settings.PLATFORM_ADMIN_EMAILS}
    return user.email.lower() in allowed


# ============================================================================
# 用户注册与登录
# ============================================================================

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user_in: UserCreate):
    """
    注册新用户。

    处理流程：
        1. 检查邮箱是否已被注册（重复注册返回 400 错误）。
        2. 使用 bcrypt 对密码进行哈希处理（不存储明文密码）。
        3. 将用户信息存入数据库。
        4. 为用户生成 JWT 访问令牌。
        5. 返回用户信息 + 令牌。

    Args:
        user_in: 包含 email 和 password 的注册请求体。
                 password 使用 SecretStr 包装，防止在日志中泄露。

    Returns:
        UserResponse: 包含用户 ID、邮箱和认证令牌的响应（HTTP 201）。

    Raises:
        HTTPException(400): 当邮箱已被注册时抛出。
    """
    # 步骤 1: 检查邮箱是否已存在
    existing_user = await database_service.get_user_by_email(user_in.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # 步骤 2: 对密码进行 bcrypt 哈希处理
    hashed_password = User.hash_password(user_in.password.get_secret_value())

    # 步骤 3: 创建用户对象
    new_user = User(
        email=user_in.email,
        hashed_password=hashed_password,
    )

    # 步骤 4: 保存到数据库
    user = await database_service.create_user(new_user)

    # 步骤 5: 生成 JWT Token（使用用户 ID 作为 subject）
    token = create_access_token(thread_id=str(user.id))

    return UserResponse(
        id=user.id,
        email=user.email,
        token=token,
        is_admin=_is_platform_admin(user),
    )


@router.post("/login", response_model=TokenResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    用户登录。

    使用 OAuth2 密码授权流程（OAuth2PasswordRequestForm）接收凭据：
    - username 字段实际承载的是用户邮箱。
    - password 字段承载明文密码。

    处理流程：
        1. 根据邮箱查找用户（不存在 → 401）。
        2. 验证密码（不匹配 → 401）。
        3. 生成并返回 JWT 访问令牌。

    安全注意事项：
        - 登录失败时不区分"邮箱不存在"和"密码错误"，
          统一返回 "Incorrect email or password"，防止用户枚举攻击。
        - 密码验证使用 bcrypt.checkpw，具有恒定时间比较特性。

    Args:
        form_data: OAuth2 密码表单数据。

    Returns:
        TokenResponse: 包含 access_token、token_type 和 expires_at 的响应。

    Raises:
        HTTPException(401): 邮箱不存在或密码错误时抛出。
    """
    # 步骤 1: 查找用户（注意 OAuth2 表单的 username 字段对应邮箱）
    user = await database_service.get_user_by_email(form_data.username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 步骤 2: 验证密码
    if not user.verify_password(form_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 步骤 3: 生成 JWT Token
    access_token = create_access_token(thread_id=str(user.id))

    return TokenResponse(
        access_token=access_token.access_token,
        token_type="bearer",
        expires_at=access_token.expires_at,
        is_admin=_is_platform_admin(user),
    )


@router.get("/me", response_model=MeResponse)
async def get_me(user: User = Depends(get_current_user)):
    """
    获取当前登录用户信息。

    前端登录后据此判断当前用户是管理员还是普通用户，
    从而决定展示完整控制台（管理员）还是仅会话页面（普通用户）。

    Returns:
        MeResponse: 包含用户 ID、邮箱和平台管理员标记。
    """
    return MeResponse(
        id=user.id,
        email=user.email,
        is_admin=_is_platform_admin(user),
    )
