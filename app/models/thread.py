"""
对话线程模型 - 对应 LangGraph 的 Thread 记录。

本模块定义了 Thread 类，用于在数据库中记录 LangGraph 的线程信息：
- 每个 Thread 的 id 与 Session 的 id 相同（一对一关系）。
- Thread 用于 LangGraph 的 Checkpoint 状态持久化。

LangGraph 使用 Thread 来组织和隔离不同对话的状态：
    每个会话（Session）对应一个 Thread，
    LangGraph 会将 Checkpoint 数据按 thread_id 分组存储。

表名：thread
"""

from datetime import (
    UTC,
    datetime,
)

from sqlmodel import (
    Field,
    SQLModel,
)


class Thread(SQLModel, table=True):
    """
    LangGraph 对话线程表模型。

    属性说明：
        id: 线程主键，与 Session.id 保持一致（一对一关系）。
        created_at: 线程创建时间（UTC 时区）。

    为什么需要独立的 Thread 表：
        LangGraph 的 Checkpoint 机制需要一个 thread_id 来组织和检索状态。
        虽然 Session 也可以直接用作 thread_id，但独立的 Thread 表：
        1. 提供了更清晰的数据边界（对话状态 vs 会话元数据）。
        2. 便于未来扩展（如为 Thread 添加额外配置参数）。
    """

    __tablename__ = "thread"

    id: str = Field(primary_key=True)  # 线程唯一标识，与 Session.id 对应
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
