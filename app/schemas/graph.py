"""
LangGraph 状态图 Schema 定义。

本模块定义了 LangGraph Agent 的状态模型 (GraphState)，
它是图执行过程中所有节点共享的状态对象。

字段说明：
    messages: 对话消息列表（使用 add_messages 支持增量更新）。
    summary: 历史对话的滚动摘要（短期记忆压缩，减少 Token 消耗）。
    active_features: 当前激活的功能开关（从 ChatRequest.features 传入）。

升级内容（v2）：
    - 新增 summary 字段：当消息超过 SUMMARY_THRESHOLD 时自动压缩旧消息。
    - 新增 active_features 字段：将功能开关传递到图状态中，供 _call_model 使用。
    - 移除 long_term_memory 字段：记忆改为工具化，不再通过 Prompt 注入。

重要提示：
    修改此文件后必须清空旧的 LangGraph Checkpoint 数据（否则状态反序列化失败）。
    执行 `docker-compose down -v` 或在数据库中手动清空 checkpoint 相关表。
"""

from typing import Annotated, Any, Dict, List, Optional

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class GraphState(BaseModel):
    """
    LangGraph Agent 的状态定义。

    该状态在 LangGraph 图的每个节点之间传递，每个节点可以：
    - 读取状态中的任何字段。
    - 返回部分更新（如 {"messages": [new_message]}）。

    messages 字段使用 add_messages 注解的原因：
        - add_messages 是 LangGraph 提供的消息合并函数。
        - 它支持增量更新：节点返回新消息时，自动追加到现有列表。
        - 避免了手动管理消息列表的合并逻辑。
    """

    # 对话消息列表
    # Annotated[list, add_messages] 表示：
    # - 类型是 list。
    # - 使用 add_messages 函数来合并新旧消息（增量更新）。
    messages: Annotated[list, add_messages] = Field(
        default_factory=list,
        description="当前对话消息列表"
    )

    # 短期记忆滚动摘要
    # 当对话消息数量超过 SUMMARY_THRESHOLD（默认 10 条）时，
    # 最旧的消息会被压缩为摘要文本，存储在此字段中。
    # 这样可以大幅减少发送给 LLM 的 Token 数量（降低成本 + 提高速度）。
    summary: str = Field(
        default="",
        description="历史对话的滚动摘要，用于压缩旧消息减少 Token 消耗"
    )

    # 当前激活的功能开关
    # 从 ChatRequest.features 传入，决定 _call_model 时绑定哪些工具。
    # 例如：{"web_search": true, "code_interpreter": true}
    # None 表示无功能激活（纯聊天模式，不绑定任何工具）。
    active_features: Optional[Dict[str, Any]] = Field(
        default=None,
        description="当前激活的功能特性开关，由前端请求传入"
    )

    agent_instructions: str = Field(
        default="",
        description="平台 Agent 注入的角色说明和运行策略"
    )

    knowledge_kb_ids: List[str] = Field(
        default_factory=list,
        description="平台 Agent 绑定的知识库 ID 列表，供知识库检索工具注入",
    )
    knowledge_top_k: int = Field(default=5, description="知识库检索 TopK")
    knowledge_score_threshold: float = Field(default=0.0, description="知识库检索最低分数阈值")
