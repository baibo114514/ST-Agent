"""
平台 Agent 配置模型。

主后端在三层架构中承担 control-plane 职责：保存 Agent 配置、校验知识库
绑定、向普通用户发布可调用的 Agent。知识正文、文档分片和检索索引由独立
knowledge-service 管理。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Dict

from sqlalchemy import Column, JSON, Text
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class PlatformAgent(SQLModel, table=True):
    """
    平台级 Agent 定义。

    status:
        draft     平台管理员编辑中，普通用户不可见。
        published 普通用户可见并可调用。
        offline   已下线，保留配置历史但不可调用。
    """

    __tablename__ = "platform_agent"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    agent_code: str = Field(nullable=False, max_length=64, unique=True, index=True)
    name: str = Field(nullable=False, max_length=255, index=True)
    description: str | None = Field(default=None, sa_column=Column(Text))
    model_name: str = Field(nullable=False, max_length=255)
    role_description: str = Field(sa_column=Column(Text, nullable=False))
    features_json: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    config_json: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    version: int = Field(default=1, nullable=False)
    status: str = Field(default="draft", max_length=32, index=True)
    created_by: int = Field(foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=utc_now, nullable=False)
    published_at: datetime | None = Field(default=None)
