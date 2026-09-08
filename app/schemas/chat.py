"""
聊天相关的 Pydantic Schema 定义。

本模块定义了聊天功能涉及的所有请求/响应数据模型：

消息模型：
    Message - 单条对话消息（user/assistant/system 角色）。

功能开关：
    FeatureFlags - 前端控制 Agent 能力的开关集合（4 个功能）。

请求/响应模型：
    ChatRequest - 聊天请求（消息列表 + 功能开关）。
    ChatResponse - 聊天响应（AI 回复消息列表）。
    StreamResponse - 流式聊天响应（逐块的文本内容）。
    ResumeRequest - 恢复会话请求（批准/拒绝 + 可选备注）。

安全设计：
    - Message.content 校验：拒绝包含 <script> 标签的消息（防 XSS）。
    - FeatureFlags 所有功能默认关闭（最小权限原则）。
    - ResumeRequest 提供明确的 approved 布尔字段（不可绕过）。
"""

import re
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class Message(BaseModel):
    """
    单条对话消息模型。

    角色说明：
    - "user": 用户发送的消息。
    - "assistant": AI 助手回复的消息。
    - "system": 系统级别的指令/提示（通常不直接暴露给用户）。

    安全校验：
    - content 长度限制：1~20000 字符。
    - 拒绝包含 <script> 标签的内容（防 XSS 攻击）。
    - 拒绝包含 null 字节的内容（可能用于绕过安全检查）。
    """
    model_config = {"extra": "ignore"}  # 忽略请求中的额外字段

    role: Literal["user", "assistant", "system"] = Field(..., description="消息发送方的角色")
    content: str = Field(..., description="消息内容", min_length=1, max_length=20000)

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        """
        验证消息内容的安全性。

        拒绝条件：
        1. 包含 <script>...</script> 标签（可能执行恶意脚本）。
        2. 包含 null 字节 (\0)（可能用于绕过字符串截断检查）。

        Args:
            v: 消息内容。

        Returns:
            str: 验证通过的消息内容。

        Raises:
            ValueError: 内容包含危险标签或 null 字节时抛出。
        """
        # 检测 <script> 标签（不区分大小写，支持跨行）
        if re.search(r"<script.*?>.*?</script>", v, re.IGNORECASE | re.DOTALL):
            raise ValueError("Content contains potentially harmful script tags")
        # 检测 null 字节
        if "\0" in v:
            raise ValueError("Content contains null bytes")
        return v


class FeatureFlags(BaseModel):
    """
    Agent 功能开关 - 前端通过此字段控制 AI 的能力范围。

    设计原则：最小权限，按需激活。所有功能默认关闭。

    四个功能开关：
    ┌───────────────────┬──────────────────────────────────────────┐
    │ 开关名             │ 功能说明                                  │
    ├───────────────────┼──────────────────────────────────────────┤
    │ web_search        │ 联网搜索（AnySearch，无 Key 自动降级 DuckDuckGo）│
    │ code_interpreter  │ Python 代码沙盒执行                        │
    │ memory_tools      │ 长期记忆（Agent 主动保存/检索用户偏好）      │
    │ email_assistant   │ 邮件助手（含 Human-in-the-loop 审批）       │
    └───────────────────┴──────────────────────────────────────────┘

    前端请求示例：
        {
            "features": {
                "web_search": true,
                "code_interpreter": false,
                "memory_tools": false,
                "email_assistant": false
            }
        }
    """
    model_config = {"extra": "ignore"}

    # 联网搜索（AnySearch，无 API Key 时自动降级为 DuckDuckGo）
    web_search: bool = Field(default=False, description="是否开启联网搜索能力")

    # Python 代码沙盒（PythonREPLTool，需要在 Docker 容器中运行以确保安全）
    code_interpreter: bool = Field(default=False, description="是否开启 Python 代码执行能力")

    # 长期记忆工具（SaveMemory + SearchMemory，Agent 主动调用）
    memory_tools: bool = Field(default=False, description="是否开启长期记忆工具")

    # 邮件助手（PrepareEmail 触发审批中断 + SendEmail 实际发送）
    email_assistant: bool = Field(default=False, description="是否开启邮件发送能力（需人工审批）")


class ChatRequest(BaseModel):
    """
    聊天请求模型。

    features 字段控制 Agent 的工具能力范围：
    - 不传或传 null → 全部功能关闭（纯聊天模式）。
    - 传具体开关 → 只激活对应工具。
    """
    messages: List[Message] = Field(
        ...,
        description="对话消息列表",
        min_length=1  # 至少一条消息
    )
    features: Optional[FeatureFlags] = Field(
        default=None,
        description="功能特性开关，控制 Agent 可用工具范围。不传则全部关闭"
    )


class ChatResponse(BaseModel):
    """聊天响应模型 - 包含 AI 的回复消息列表。"""
    messages: List[Message] = Field(..., description="对话消息列表")


class StreamResponse(BaseModel):
    """流式聊天响应模型 - 单个流式块的内容。"""
    content: str = Field(default="", description="当前流式块的内容")
    done: bool = Field(default=False, description="是否已完成流式输出")


class ResumeRequest(BaseModel):
    """
    恢复被中断会话的请求模型（审批结果）。

    当 Agent 触发 Human-in-the-loop 暂停（如邮件审批）后，前端提交此模型
    批准或拒绝继续执行。session_id 走路径参数（POST /sessions/{id}/resume）。

    工作流程：
        1. Agent 调用 prepare_email → Graph 暂停。
        2. 前端检测到暂停信号 → 展示审批 UI。
        3. 用户操作 → 调用 POST /sessions/{session_id}/resume 传入此模型。
        4. 后端向 Graph 发送 Command(resume="approved"/"rejected")。
        5. Agent 继续执行或取消。
    """
    approved: bool = Field(..., description="true=批准继续，false=拒绝继续")
    human_response: Optional[Dict] = Field(
        default=None,
        description="传给 LangGraph 的完整响应对象，不传时自动构建"
    )
