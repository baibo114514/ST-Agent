"""
聊天会话模型 - 定义会话(Session)的数据库表结构。

本模块定义了 Session 类，对应数据库中的 session 表：
- 每个会话属于一个用户（多对一关系）。
- 每个会话对应一个 LangGraph Thread（用于状态持久化）。
- 会话包含名称和创建时间。

表名：session

关系说明：
    User (1) ──── (N) Session
    一个用户可以有多个聊天会话，一个会话只属于一个用户。

循环导入处理：
    使用 TYPE_CHECKING 条件导入 User 模型。
    TYPE_CHECKING 只在静态类型检查时为 True，运行时为 False。
    这避免了 User ↔ Session 之间的循环导入问题。
"""

from typing import (
    TYPE_CHECKING,  # 类型检查专用变量，运行时为 False
    List,
)

from sqlmodel import (
    Field,
    Relationship,  # SQLModel 关系定义，用于声明表之间的关联
)

from app.models.base import BaseModel

# 仅在类型检查时导入 User，避免运行时循环导入
# 因为 User 也导入了 Session（通过 Relationship），
# 如果直接 import User 会导致循环依赖错误
if TYPE_CHECKING:
    from app.models.user import User


class Session(BaseModel, table=True):
    """
    聊天会话表模型。

    属性说明：
        id: 会话主键（UUID 字符串），同时作为 LangGraph thread_id 使用。
        user_id: 外键，关联到 user 表的 id，标识会话所属用户。
        name: 会话名称，默认为空字符串。前端可让用户自定义命名。
        created_at: 会话创建时间（UTC，继承自 BaseModel）。
        user: 反向关系，通过 session.user 可访问所属的 User 对象。

    关系说明：
        - Session → User: 多对一（多个会话属于一个用户）。
        - User → Session: 一对多（一个用户拥有多个会话）。
        - Relationship(back_populates="sessions") 表示在 User 模型中
          存在对应的 back_populates="user" 关系属性。
    """

    __tablename__ = "session"

    id: str = Field(primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    name: str = Field(default="")
    # 反向关系：session.user 可以获取所属的 User 对象
    # back_populates="sessions" 对应 User 模型中的 sessions 属性
    user: "User" = Relationship(back_populates="sessions")
