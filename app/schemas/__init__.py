"""
Schemas 包 - 统一导出所有 Pydantic 模型。

本模块作为 schemas 包的入口，集中导出所有对外可用的 Schema 类，
方便其他模块通过 `from app.schemas import Xxx` 直接引用。

导出的 Schema 分类：
- 认证相关：Token
- 平台 Agent：PlatformAgentWrite, PlatformAgentResponse
- 聊天相关：ChatRequest, ChatResponse, FeatureFlags, Message, StreamResponse
- 图状态：GraphState
"""

from app.schemas.agent import (
    AgentFeatureConfig,
    AgentKnowledgeConfig,
    PlatformAgentPage,
    PlatformAgentResponse,
    PlatformAgentStatusUpdate,
    PlatformAgentWrite,
    PublicAgentPage,
    PublicAgentItem,
)
from app.schemas.auth import Token
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    FeatureFlags,
    Message,
    StreamResponse,
)
from app.schemas.graph import GraphState

# __all__ 定义了 `from app.schemas import *` 时导出的符号列表
__all__ = [
    "Token",
    "AgentFeatureConfig",
    "AgentKnowledgeConfig",
    "PlatformAgentPage",
    "PlatformAgentResponse",
    "PlatformAgentStatusUpdate",
    "PlatformAgentWrite",
    "PublicAgentPage",
    "PublicAgentItem",
    "ChatRequest",
    "ChatResponse",
    "FeatureFlags",
    "Message",
    "StreamResponse",
    "GraphState",
]
