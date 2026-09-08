"""
Services 包 - 统一导出所有服务层组件。

本模块将 services 子包组织为一个 Python Package，
并显式导出供外部使用的核心服务对象。

导出的服务：
- agent_config_service: 平台 Agent 配置服务。
- database_service: 数据库服务单例（DatabaseService 实例）。
- knowledge_service_client: 独立 knowledge-service HTTP 客户端。
- LLMRegistry: 大语言模型注册表类。
- llm_service: LLM 服务单例（LLMService 实例）。
"""

from app.services.agent_config import agent_config_service
from app.services.database import database_service
from app.services.knowledge_client import knowledge_service_client
from app.services.llm import (
    LLMRegistry,
    llm_service,
)

__all__ = [
    "agent_config_service",
    "database_service",
    "knowledge_service_client",
    "LLMRegistry",
    "llm_service",
]
