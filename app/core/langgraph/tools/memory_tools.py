"""
长期记忆工具 - 允许 Agent 主动保存和检索用户信息。

本模块提供两个工具，让 AI Agent 能够管理用户的长期记忆：

1. save_memory_tool（保存记忆）：
   - Agent 判断用户说了值得记住的信息时主动调用。
   - 将内容存入 memory 表，关联到当前用户。
   - 例如：用户说"我喜欢 Python"，Agent 可保存此偏好。

2. search_memory_tool（检索记忆）：
   - Agent 需要了解用户历史偏好时调用。
   - 从 memory 表中查询该用户的所有记忆。
   - 例如：新对话中，Agent 可先检索用户之前的偏好设置。

与短期记忆的区别：
    - 短期记忆（summary）：自动管理的对话摘要，随对话进行自动更新。
    - 长期记忆（memory）：Agent 主动管理的关键信息，跨会话持久化。

设计理念：
    将记忆从 Prompt 注入改为工具化，让 Agent 自己决定何时保存/检索，
    而不是每次对话都注入全部记忆（减少 Token 消耗，提高相关性）。
"""

import json
from typing import List, Optional
from langchain_core.tools import tool
from sqlmodel import Session, select
from app.services.database import database_service
from app.models.memory import Memory
from app.core.logging import logger


@tool
def save_memory_tool(content: str, user_id: str) -> str:
    """
    将重要信息保存到用户的长期记忆中。

    Agent 应该在以下情况调用此工具：
    - 用户明确表达了偏好或要求（如"记住我喜欢用中文"）。
    - 用户分享了重要的个人信息（如"我叫张三"）。
    - 对话中产生了需要跨会话保留的关键结论。

    Args:
        content: 要保存的记忆内容（会被去除首尾空白）。
        user_id: 用户 ID（字符串格式，兼容整数和非整数 ID）。

    Returns:
        str: 保存成功的确认消息，或失败的错误描述。
    """
    try:
        # 用户 ID 兼容处理：尝试转为整数（数据库存储格式），失败则保留原值
        try:
            uid = int(user_id)
        except ValueError:
            uid = user_id

        with Session(database_service.engine) as session:
            # 创建记忆对象并保存
            memory = Memory(user_id=uid, content=content.strip())
            session.add(memory)
            session.commit()

            logger.info("memory_saved_to_db", user_id=uid, content=content[:50])
            return f"记忆已成功保存：'{content}'"
    except Exception as e:
        logger.error("save_memory_failed", error=str(e), user_id=user_id)
        return f"保存失败：{str(e)}"


@tool
def search_memory_tool(query: str, user_id: str) -> str:
    """
    在用户的长期记忆中搜索相关信息。

    Agent 应该在以下情况调用此工具：
    - 对话开始时，了解用户之前的偏好和背景。
    - 用户的问题暗示之前可能讨论过相关话题。
    - 需要确认用户之前的设置或选择。

    注意：当前实现返回用户的所有记忆（不做语义搜索），
    未来可升级为基于向量的语义相似度搜索。

    Args:
        query: 搜索查询字符串（当前版本未使用，为未来语义搜索预留）。
        user_id: 用户 ID（字符串格式）。

    Returns:
        str: 格式化的记忆列表，或"没有找到"的提示。
    """
    try:
        # 用户 ID 兼容处理
        try:
            uid = int(user_id)
        except ValueError:
            uid = user_id

        with Session(database_service.engine) as session:
            # 查询该用户的所有记忆
            statement = select(Memory).where(Memory.user_id == uid)
            results = session.exec(statement).all()

            if not results:
                return "没有找到相关的历史记忆。"

            # 格式化为列表展示
            memory_texts = [m.content for m in results]
            formatted_results = "\n".join([f"- {text}" for text in memory_texts])
            return f"找到以下相关记忆：\n{formatted_results}"

    except Exception as e:
        logger.error("search_memory_failed", error=str(e), user_id=user_id)
        return f"检索记忆时出错：{str(e)}"
