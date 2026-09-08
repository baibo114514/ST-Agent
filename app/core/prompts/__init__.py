"""
提示词管理模块 - 加载和格式化系统提示(System Prompt)模板。

本模块负责：
1. 从 system.md 文件加载系统提示模板。
2. 使用传入的参数对模板进行格式化（替换占位符）。
3. 注入默认参数值，防止模板中缺少某些变量导致格式化失败。

系统提示模板的作用：
    System Prompt 是发送给 LLM 的第一条消息，定义了 AI 助手的：
    - 角色身份（如"你是一个知识库助手"）。
    - 行为规范（如"优先使用工具检索"）。
    - 可用能力（如"你可以搜索网页、执行代码"）。

模板占位符说明：
    {agent_name}           — 助手名称（来自 PROJECT_NAME 配置）。
    {current_date_and_time} — 当前日期时间（让 AI 知道"现在是什么时候"）。
    {user_id}              — 当前用户 ID。
    {summary}              — 历史对话的滚动摘要（用于短期记忆）。
    {custom_instructions}  — 动态注入的特殊指令（如知识库检索规则）。
"""

import os
from datetime import datetime

from app.core.config import settings


def load_system_prompt(**kwargs):
    """
    加载系统提示模板并用传入的参数进行格式化。

    工作流程：
    1. 读取 app/core/prompts/system.md 文件的内容。
    2. 准备默认参数（确保即使调用方没有传递某个参数也不会报错）。
    3. 合并默认参数和传入参数（传入参数优先级更高）。
    4. 使用 Python 字符串的 format() 方法替换模板占位符。

    Args:
        **kwargs: 传递给模板的变量值。支持的变量包括：
            - agent_name: 助手名称。
            - current_date_and_time: 当前日期时间。
            - user_id: 用户 ID。
            - summary: 对话摘要。
            - custom_instructions: 自定义指令。

    Returns:
        str: 格式化后的系统提示字符串，可直接作为 SystemMessage 发送给 LLM。

    示例：
        prompt = load_system_prompt(
            user_id="123",
            summary="用户之前讨论了 Python 编程",
            custom_instructions="请使用中文回答"
        )
    """
    # 读取模板文件
    with open(os.path.join(os.path.dirname(__file__), "system.md"), "r", encoding="utf-8") as f:
        template = f.read()

        # 准备默认参数 — 确保模板中的占位符都有对应值，防止 KeyError
        default_kwargs = {
            "agent_name": f"{settings.PROJECT_NAME} Agent",
            "current_date_and_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user_id": "unknown",
            "summary": "",
            "custom_instructions": ""  # 新增默认值，防止未传时模板格式化报错
        }

        # 合并参数：传入参数覆盖默认参数
        format_kwargs = {**default_kwargs, **kwargs}

        # 执行格式化：将 {变量名} 替换为实际值
        return template.format(**format_kwargs)
