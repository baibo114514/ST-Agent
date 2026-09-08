"""
平台 Agent 配置 API Schema。
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AgentFeatureConfig(BaseModel):
    """Agent 可用工具开关。知识库由独立配置控制，不作为普通工具开关保存。"""

    model_config = ConfigDict(extra="ignore")

    web_search: bool = Field(default=False, description="是否允许联网搜索")
    code_interpreter: bool = Field(default=False, description="是否允许代码解释器")
    memory_tools: bool = Field(default=False, description="是否允许长期记忆工具")
    email_assistant: bool = Field(default=False, description="是否允许邮件助手")


class AgentKnowledgeConfig(BaseModel):
    """平台 Agent 的知识库检索配置。"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    enabled: bool = Field(default=False)
    kb_ids: List[str] = Field(default_factory=list, alias="kbIds")
    top_k: int = Field(default=5, ge=1, le=20, alias="topK")
    score_threshold: float = Field(default=0, ge=0, alias="scoreThreshold")

    @field_validator("kb_ids")
    @classmethod
    def validate_kb_ids(cls, value: List[str]) -> List[str]:
        seen = set()
        normalized = []
        for item in value:
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        if len(normalized) > 10:
            raise ValueError("at most 10 knowledge bases may be bound")
        return normalized


class PlatformAgentWrite(BaseModel):
    """平台管理员创建/更新 Agent 的请求体。"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    agent_code: str = Field(..., min_length=2, max_length=64, alias="agentCode")
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    model_name: str = Field(default="deepseek-chat", min_length=1, max_length=255, alias="modelName")
    role_description: str = Field(..., min_length=1, max_length=12000, alias="roleDescription")
    features: AgentFeatureConfig = Field(default_factory=AgentFeatureConfig)
    knowledge: AgentKnowledgeConfig = Field(default_factory=AgentKnowledgeConfig)
    config: Dict[str, Any] = Field(default_factory=dict)


class PlatformAgentStatusUpdate(BaseModel):
    """平台 Agent 状态变更请求。"""

    status: Literal["draft", "published", "offline"]


class PlatformAgentResponse(BaseModel):
    """平台 Agent 配置响应。"""

    model_config = ConfigDict(populate_by_name=True)

    agent_id: str = Field(alias="agentId")
    agent_code: str = Field(alias="agentCode")
    name: str
    description: Optional[str] = None
    model_name: str = Field(alias="modelName")
    role_description: str = Field(alias="roleDescription")
    features: AgentFeatureConfig
    knowledge: AgentKnowledgeConfig
    config: Dict[str, Any]
    version: int
    status: str
    created_by: int = Field(alias="createdBy")
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")
    published_at: Optional[str] = Field(default=None, alias="publishedAt")


class PlatformAgentPage(BaseModel):
    items: List[PlatformAgentResponse]
    total: int


class PublicAgentItem(BaseModel):
    """普通用户可见的 Agent 目录项。"""

    model_config = ConfigDict(populate_by_name=True)

    agent_id: str = Field(alias="agentId")
    agent_code: str = Field(alias="agentCode")
    name: str
    description: Optional[str] = None
    model_name: str = Field(alias="modelName")
    features: AgentFeatureConfig
    knowledge: AgentKnowledgeConfig
    version: int
    status: str


class PublicAgentPage(BaseModel):
    items: List[PublicAgentItem]
    total: int
