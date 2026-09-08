"""
数据库服务层 - 封装所有 CRUD 操作，提供统一的数据库访问接口。

本模块实现了 DatabaseService 类，作为应用与 PostgreSQL 数据库之间的服务层：
- 用户操作：创建用户、按邮箱查询、按 ID 查询。
- 会话操作：创建会话（同时创建 LangGraph Thread）、查询会话列表、删除会话。
- 健康检查：验证数据库连接是否正常。

设计原则：
1. 单例模式：整个应用共享一个 DatabaseService 实例 (database_service)。
2. 同步引擎 + 异步方法：使用 SQLModel 的同步 Session，在 FastAPI 线程池中执行。
3. 连接池：通过 SQLAlchemy QueuePool 管理数据库连接，避免频繁创建/销毁连接。

修复记录：
- [Fix-Table] 显式导入 Memory 和 PlatformAgent 模型。
  确保 create_db_and_tables() 能自动创建记忆表和平台 Agent 配置表。
  SQLModel 只有在模块被导入时才会注册模型，如果忘记导入，表就不会被创建。
"""

import asyncio
from typing import (
    List,
    Optional,
)

from fastapi import HTTPException
from psycopg import AsyncConnection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import QueuePool
from sqlmodel import (
    Session,
    SQLModel,
    create_engine,
    select,
)

from app.core.config import settings
from app.core.logging import logger
from app.models.agent import PlatformAgent
# [Fix] 显式导入 Memory 以确保 SQLModel 能发现并创建该表
from app.models.memory import Memory
from app.models.session import Session as ChatSession
from app.models.thread import Thread
from app.models.user import User


class DatabaseService:
    """
    数据库服务 - 提供所有数据库操作的统一入口。

    职责：
    - 管理数据库引擎和连接池的生命周期。
    - 封装用户、会话等实体的 CRUD 操作。
    - 提供数据库健康检查能力。

    使用 QueuePool 连接池的好处：
    - 复用数据库连接，避免每次请求都创建新连接。
    - 限制最大连接数，防止数据库连接耗尽。
    - 自动管理连接的创建、复用和回收。
    """

    def __init__(self):
        # 构建 PostgreSQL 连接 URL
        # 格式：postgresql+psycopg://用户名:密码@主机:端口/数据库名
        database_url = (
            f"postgresql+psycopg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
            f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
        )
        # 创建 SQLAlchemy 引擎，配置连接池参数
        self.engine = create_engine(
            database_url,
            pool_size=settings.POSTGRES_POOL_SIZE,        # 连接池最大连接数（默认 20）
            max_overflow=settings.POSTGRES_MAX_OVERFLOW,  # 超出 pool_size 时允许的额外连接数（默认 10）
            poolclass=QueuePool,                           # 使用队列连接池（FIFO 顺序）
        )

    def create_db_and_tables(self):
        """
        创建所有已注册模型对应的表。

        SQLModel.metadata.create_all() 会扫描所有已导入且继承自 SQLModel 的类，
        并在数据库中创建对应的表（已存在的表会被跳过）。
        因此必须在文件顶部显式导入所有需要建表的模型。
        """
        SQLModel.metadata.create_all(self.engine)

    # ========================================================================
    # 用户操作 (User Operations)
    # ========================================================================

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """
        根据邮箱地址查找用户。

        常用于登录和注册流程中检查邮箱是否已被占用。

        Args:
            email: 用户邮箱地址。

        Returns:
            Optional[User]: 找到的用户对象，如果邮箱不存在则返回 None。
        """
        with Session(self.engine) as session:
            statement = select(User).where(User.email == email)
            return session.exec(statement).first()

    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        """
        根据用户 ID 查找用户。

        常用于认证流程中根据 Token 中的 user_id 获取当前用户信息。

        Args:
            user_id: 用户的数据库自增 ID。

        Returns:
            Optional[User]: 找到的用户对象，如果 ID 不存在则返回 None。
        """
        with Session(self.engine) as session:
            return session.get(User, user_id)

    async def create_user(self, user: User) -> User:
        """
        创建新用户并保存到数据库。

        用户注册时调用，密码应在传入前通过 User.hash_password() 进行哈希处理。

        Args:
            user: 包含 email 和 hashed_password 的 User 对象（id 由数据库自动生成）。

        Returns:
            User: 创建成功的用户对象（id 已填充）。

        Raises:
            HTTPException(400): 当邮箱重复或发生数据库错误时抛出。
        """
        try:
            with Session(self.engine) as session:
                session.add(user)
                session.commit()
                # refresh 获取数据库生成的 id 和 created_at 等字段
                session.refresh(user)
                return user
        except SQLAlchemyError as e:
            logger.exception("create_user_failed", error=str(e))
            raise HTTPException(
                status_code=400, detail="User already exists or database error"
            )

    # ========================================================================
    # 会话操作 (Session Operations)
    # ========================================================================

    async def create_session(
        self, user_id: int, name: str, session_id: str
    ) -> ChatSession:
        """
        创建新的聊天会话。

        该操作会在一个事务中同时完成两件事：
        1. 在 session 表中创建聊天会话记录（关联到用户）。
        2. 在 thread 表中创建对应的 LangGraph 线程记录（用于状态持久化）。

        这两个操作必须在同一事务中，确保数据一致性。

        Args:
            user_id: 所属用户的数据库 ID。
            name: 会话名称（经过净化处理的用户输入）。
            session_id: 会话的唯一标识符（UUID 字符串）。

        Returns:
            ChatSession: 创建成功的会话对象。
        """
        with Session(self.engine) as session:
            # 1. 创建聊天会话记录
            chat_session = ChatSession(id=session_id, user_id=user_id, name=name)
            session.add(chat_session)

            # 2. 同时创建 LangGraph 需要的 Thread 记录
            #    Thread 的 id 与 Session 的 id 相同，确保一一对应
            thread = Thread(id=session_id)
            session.add(thread)

            session.commit()
            session.refresh(chat_session)
            return chat_session

    async def get_user_sessions(self, user_id: int) -> List[ChatSession]:
        """
        获取指定用户的所有聊天会话，按创建时间倒序排列。

        Args:
            user_id: 用户的数据库 ID。

        Returns:
            List[ChatSession]: 会话列表，最新的会话排在最前面。
        """
        with Session(self.engine) as session:
            statement = (
                select(ChatSession)
                .where(ChatSession.user_id == user_id)
                .order_by(ChatSession.created_at.desc())
            )
            return session.exec(statement).all()

    async def get_session(self, session_id: str) -> Optional[ChatSession]:
        """
        根据会话 ID 查找会话。

        Args:
            session_id: 会话的唯一标识符。

        Returns:
            Optional[ChatSession]: 找到的会话对象，如果 ID 不存在则返回 None。
        """
        with Session(self.engine) as session:
            return session.get(ChatSession, session_id)

    async def delete_session(self, session_id: str):
        """
        删除指定的聊天会话。

        注意：此操作不会级联删除 LangGraph 的 checkpoint 数据，
        清空 checkpoint 需要额外的操作（参见 Chatbot.clear_chat_history）。

        Args:
            session_id: 要删除的会话 ID。
        """
        with Session(self.engine) as session:
            chat_session = session.get(ChatSession, session_id)
            if chat_session:
                session.delete(chat_session)
                session.commit()

    # ========================================================================
    # 健康检查 (Health Check)
    # ========================================================================

    async def health_check(self) -> bool:
        """
        验证数据库连接是否正常。

        通过执行轻量级的 SELECT 1 查询来检测：
        - 数据库服务器是否可达。
        - 连接池是否能正常工作。
        - 当前用户是否有查询权限。

        Returns:
            bool: True 表示数据库正常，False 表示连接异常。
        """
        database_url = (
            f"postgresql://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
            f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
        )
        try:
            connection = await asyncio.wait_for(
                AsyncConnection.connect(database_url, autocommit=True),
                timeout=5,
            )
            try:
                async with connection.cursor() as cursor:
                    await cursor.execute("SELECT 1")
                    await cursor.fetchone()
            finally:
                await connection.close()
            return True
        except Exception:
            return False


# ============================================================================
# 全局单例实例
# ============================================================================
# 整个应用共享同一个 DatabaseService 实例
# 通过 `from app.services.database import database_service` 引用
database_service = DatabaseService()
