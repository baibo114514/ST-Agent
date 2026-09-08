"""
认证相关的 Pydantic Schema 定义。

本模块定义了用户认证、注册、会话相关的请求/响应数据模型：
- Token / TokenResponse : JWT 令牌的响应模型。
- UserCreate : 用户注册请求模型（含密码强度校验）。
- UserResponse : 用户注册/登录成功后的响应模型。
- SessionResponse : 会话创建/查询的响应模型（含名称净化）。

Pydantic Schema vs SQLModel Model：
    - Schema (本模块): 定义 API 请求/响应的数据格式和校验规则。
    - Model (app/models/): 定义数据库表结构。
    两者分离的好处：可以独立演化（如 API 增加字段但数据库不变）。
"""

import re
from datetime import datetime

from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
)


class Token(BaseModel):
    """
    JWT 访问令牌模型。

    包含令牌字符串、类型和过期时间，可嵌入其他响应模型中使用。
    也作为 create_access_token() 函数的返回值类型。

    属性说明：
        access_token: JWT 令牌字符串（Base64 编码）。
        token_type: 令牌类型，固定为 "bearer"（符合 OAuth2 规范）。
        expires_at: 令牌过期时间（UTC 时间戳）。
    """
    access_token: str = Field(..., description="JWT 访问令牌字符串")
    token_type: str = Field(default="bearer", description="令牌类型，目前仅支持 bearer")
    expires_at: datetime = Field(..., description="令牌过期时间（UTC 时间）")


class TokenResponse(BaseModel):
    """
    登录接口的响应模型。

    字段与 Token 相同，但作为独立的响应模型便于未来扩展
    （例如添加 refresh_token 字段而不影响其他使用 Token 的地方）。
    """
    access_token: str = Field(..., description="JWT 访问令牌")
    token_type: str = Field(default="bearer", description="令牌类型，固定为 bearer")
    expires_at: datetime = Field(..., description="令牌过期时间（UTC）")
    is_admin: bool = Field(default=False, description="是否为平台管理员")


class UserCreate(BaseModel):
    """
    用户注册请求模型。

    用于接收客户端提交的注册信息，并对密码进行强度校验：
    - 长度 8~64 位。
    - 必须包含大写字母、小写字母、数字和特殊字符。

    安全设计：
        password 使用 SecretStr 类型：
        - 在日志输出和 repr() 中自动隐藏（显示为 "********"）。
        - 需要显式调用 get_secret_value() 才能获取明文。
        - 防止密码意外泄露到日志文件。
    """
    email: EmailStr = Field(..., description="用户邮箱地址，需符合 Email 格式")
    password: SecretStr = Field(
        ...,
        description="用户密码，长度 8~64 位，必须包含大小写字母、数字和特殊字符",
        min_length=8,
        max_length=64
    )

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: SecretStr) -> SecretStr:
        """
        自定义密码强度校验器。

        校验规则：
        1. 长度至少 8 个字符。
        2. 至少一个大写字母 (A-Z)。
        3. 至少一个小写字母 (a-z)。
        4. 至少一个数字 (0-9)。
        5. 至少一个特殊字符 (!@#$%^&*等)。

        Args:
            v: 包装在 SecretStr 中的密码。

        Returns:
            SecretStr: 验证通过后原样返回。

        Raises:
            ValueError: 当密码不满足任何一条强度规则时抛出。
        """
        password = v.get_secret_value()  # 仅在需要校验时获取明文

        # 逐条校验，任意一条不满足都立即报错
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not re.search(r"[A-Z]", password):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", password):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"[0-9]", password):
            raise ValueError("Password must contain at least one number")
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            raise ValueError("Password must contain at least one special character")

        return v


class UserResponse(BaseModel):
    """
    用户操作响应模型（注册或登录成功后返回）。

    包含用户基本信息和认证令牌，方便客户端后续请求携带认证信息。
    """
    id: int = Field(..., description="用户唯一标识 ID")
    email: str = Field(..., description="用户邮箱地址")
    token: Token = Field(..., description="认证令牌信息，包含 access_token、token_type 和过期时间")
    is_admin: bool = Field(default=False, description="是否为平台管理员")


class MeResponse(BaseModel):
    """当前登录用户信息，用于前端区分管理员与普通用户角色。"""

    id: int = Field(..., description="用户唯一标识 ID")
    email: str = Field(..., description="用户邮箱地址")
    is_admin: bool = Field(..., description="是否为平台管理员")


class SessionResponse(BaseModel):
    """
    会话创建/查询响应模型。

    返回会话的 ID、名称以及专属的 JWT Token，用于后续消息请求的认证。
    """
    session_id: str = Field(..., description="会话的唯一标识符，通常为 UUID")
    name: str = Field(
        default="",
        description="会话名称，最长 100 字符，自动去除可能引起注入的字符",
        max_length=100
    )
    token: Token = Field(..., description="该会话的认证令牌，用于后续消息请求的身份验证")

    @field_validator("name")
    @classmethod
    def sanitize_name(cls, v: str) -> str:
        """
        对会话名称进行安全净化处理。

        移除可能用于 XSS 或注入攻击的危险字符：
        - HTML 标签字符：< > { } [ ] ( )
        - 引号字符：' " `
        - 这些字符在渲染到前端时可能被解释为代码。

        Args:
            v: 原始会话名称。

        Returns:
            str: 净化后的名称字符串。
        """
        sanitized = re.sub(r'[<>{}[\]()\'"`]', "", v)
        return sanitized
