"""
长期记忆模型 - 存储用户的重要信息以备跨会话回忆。

本模块定义了 Memory 数据库表：
- 允许 AI Agent 在对话过程中主动保存用户认为重要的信息。
- 在后续对话中，Agent 可以检索之前保存的记忆，实现跨会话的上下文感知。

表名：memory

使用示例：
    # Agent 调用 save_memory_tool 保存记忆
    save_memory_tool(content="用户喜欢 Python 编程", user_id="123")

    # Agent 调用 search_memory_tool 检索记忆
    search_memory_tool(query="编程偏好", user_id="123")
    # → "找到以下相关记忆：\n- 用户喜欢 Python 编程"
"""

from datetime import UTC, datetime
from typing import Optional
from sqlmodel import Field, SQLModel


class Memory(SQLModel, table=True):
    """
    用户长期记忆表。

    每条记录代表一条用户特定的记忆信息：
    - id: 自增主键。
    - user_id: 关联的用户 ID（与 User.id 对应），并建立索引以加速按用户查询。
    - content: 记忆内容文本（不能为空）。
    - created_at: 记忆创建时间（UTC）。

    索引设计：
        user_id 列建立了索引，因为检索记忆时总是按用户查询。
        这确保了即使有大量用户的记忆数据，单个用户的查询性能也不会下降。
    """

    __tablename__ = "memory"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)  # 用户 ID，建立索引加速按用户查询
    content: str = Field(nullable=False)  # 记忆内容，不允许为空
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        nullable=False
    )
