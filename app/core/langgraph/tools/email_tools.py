"""
邮件发送工具 - 带 Human-in-the-loop（人工审批）中断机制。

本模块实现了安全可控的邮件发送功能：

工作流程（两阶段）：
  阶段 1 - prepare_email（准备草稿）：
    1. Agent 调用 prepare_email，提供收件人、主题、正文。
    2. 工具触发 LangGraph 的 interrupt() 暂停执行。
    3. 前端展示邮件预览卡片（收件人、主题、正文）。
    4. 等待用户审批。

  阶段 2 - send_email（实际发送）：
    1. 用户点击"批准"后，Agent 自动调用 send_email。
    2. 工具使用 SMTP 协议发送邮件（支持 SSL/TLS）。
    3. 返回发送成功或失败的消息。

安全设计：
  - 双重确认：Agent 不能直接发邮件，必须经过 prepare_email → 人工审批 → send_email。
  - 线程隔离：SMTP 发送在线程池中执行，不阻塞事件循环。
  - 认证信息分离：SMTP 密码从 settings 中读取，永不暴露给 Agent。

Bug 修复记录：
  - [Fix-10] 修复 "RuntimeError: This event loop is already running"：
    使用独立线程池 + 新事件循环执行同步 SMTP 操作。
  - [Fix-SMTP] 修复 QQ 邮箱 "550 The 'From' header is missing or invalid"：
    采用"信封与信纸分离"策略 — 信纸上写收件人友好的显示名称，
    SMTP 协议层使用纯邮箱地址作为 MAIL FROM。
"""

import asyncio
import smtplib
import ssl
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from email.utils import formataddr
from typing import Optional, Type

from langchain_core.tools import BaseTool
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import logger

# ============================================================================
# 共享线程池
# ============================================================================

# 专用线程池用于执行阻塞的 SMTP 操作
# max_workers=2：邮件发送通常不需要高并发
_thread_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="email_tool")


def _run_async_safely(coro):
    """
    在同步上下文中安全执行异步协程。

    用于 LangChain BaseTool._run()（同步方法）调用我们的异步实现。
    通过创建独立的事件循环来隔离异步操作，避免"事件循环已在运行"的错误。

    Args:
        coro: 要执行的异步协程。

    Returns:
        协程的执行结果。
    """
    def run_in_thread():
        # 在线程中创建新的事件循环（与主事件循环隔离）
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    future = _thread_pool.submit(run_in_thread)
    return future.result()


# ============================================================================
# 工具输入 Schema
# ============================================================================

class PrepareEmailInput(BaseModel):
    """prepare_email 工具的输入 Schema。"""
    to_email: str = Field(..., description="收件人邮箱地址")
    subject: str = Field(..., description="邮件主题")
    body: str = Field(..., description="邮件正文内容（支持纯文本）")
    to_name: Optional[str] = Field(default="", description="收件人姓名（可选）")


class SendEmailInput(BaseModel):
    """send_email 工具的输入 Schema。"""
    to_email: str = Field(..., description="收件人邮箱地址")
    subject: str = Field(..., description="邮件主题")
    body: str = Field(..., description="邮件正文内容")
    to_name: Optional[str] = Field(default="", description="收件人姓名")


# ============================================================================
# 邮件准备工具 — 触发人工审批中断
# ============================================================================

class PrepareEmailTool(BaseTool):
    """
    邮件准备工具 — 构建邮件草稿并请求人工审批。

    调用此工具后，LangGraph 的 interrupt() 会暂停图执行，
    前端展示审批卡片，等待用户确认后才继续。
    """

    name: str = "prepare_email"
    description: str = (
        "准备邮件内容并请求用户审批。"
        "在真正发送邮件前，会向用户展示邮件预览，等待确认后才执行发送。"
        "这是高风险操作，必须经过人工审批。"
        "输入：收件人邮箱、主题、正文内容。"
    )
    args_schema: Type[BaseModel] = PrepareEmailInput

    def _run(self, to_email: str, subject: str, body: str, to_name: str = "") -> str:
        """同步调用入口 → 委托给异步实现。"""
        return _run_async_safely(self._arun(to_email, subject, body, to_name))

    async def _arun(self, to_email: str, subject: str, body: str, to_name: str = "") -> str:
        """
        构建邮件预览并触发 interrupt 中断。

        interrupt() 是 LangGraph 提供的暂停机制：
        - 图执行在此处暂停。
        - 保存邮件预览数据到 Checkpoint。
        - 前端获取 snapshot.next 检测到暂停。
        - 用户审批后，前端调用 /chatbot/resume。
        - 图恢复执行，中断点返回用户的审批结果。

        Args:
            to_email: 收件人邮箱。
            subject: 邮件主题。
            body: 邮件正文。
            to_name: 收件人姓名。

        Returns:
            str: 审批结果消息（批准时提示 Agent 调用 send_email，拒绝时告知原因）。
        """
        email_preview = {
            "to_email": to_email,
            "to_name": to_name,
            "subject": subject,
            "body": body,
            "from": settings.EMAIL_SMTP_USER
        }

        logger.info("email_approval_requested", **email_preview)

        # 触发 LangGraph 中断 — 图在此暂停
        human_review = interrupt(email_preview)

        # 用户审批后，interrupt() 返回审批结果
        if str(human_review).lower() in ["approved", "true", "yes"]:
            return (
                f"用户已批准发送邮件。"
                f"请立即调用 send_email 工具，参数："
                f"to_email={to_email}, subject={subject}, body={body}, to_name={to_name}"
            )
        else:
            return f"用户拒绝了发送邮件请求。原因/备注：{human_review}"


# ============================================================================
# 邮件发送工具 — 实际执行 SMTP 发送
# ============================================================================

class SendEmailTool(BaseTool):
    """
    邮件发送工具 — 通过 SMTP 实际发送邮件。

    仅在 prepare_email 获得用户批准后由 Agent 调用。
    使用 Python 标准库 smtplib 发送邮件，支持 SSL/TLS 加密。
    """

    name: str = "send_email"
    description: str = (
        "发送邮件（仅在 prepare_email 工具获得用户批准后调用）。"
        "使用 SMTP 协议真正发出邮件。"
        "输入：收件人邮箱、主题、正文、收件人姓名。"
    )
    args_schema: Type[BaseModel] = SendEmailInput

    def _run(self, to_email: str, subject: str, body: str, to_name: str = "") -> str:
        """同步调用入口 → 委托给异步实现。"""
        return _run_async_safely(self._arun(to_email, subject, body, to_name))

    async def _arun(self, to_email: str, subject: str, body: str, to_name: str = "") -> str:
        """
        通过 SMTP 发送邮件。

        QQ 邮箱适配（信封与信纸分离策略）：
        - 信纸（EmailMessage）：包含中文发件人名称 + 邮箱，用于收件人展示。
        - 信封（SMTP MAIL FROM）：使用纯邮箱地址，确保通过 QQ 邮箱的格式校验。
        之前使用 send_message() 会从 msg['From'] 提取发件人，
        如果包含中文名称会导致 QQ 邮箱返回 "550 The 'From' header is missing or invalid"。

        Args:
            to_email: 收件人邮箱。
            subject: 邮件主题。
            body: 邮件正文。
            to_name: 收件人姓名。

        Returns:
            str: 发送结果消息（成功或失败的详细描述）。
        """
        smtp_host = settings.EMAIL_SMTP_HOST
        smtp_port = settings.EMAIL_SMTP_PORT
        smtp_user = settings.EMAIL_SMTP_USER
        smtp_password = settings.EMAIL_SMTP_PASSWORD

        # 步骤 1: 构建邮件对象（信纸 — 给收件人看的）
        msg = EmailMessage()
        msg.set_content(body)
        msg["Subject"] = subject
        # formataddr 格式化发件人：'智能助手 <user@qq.com>'
        msg["From"] = formataddr((settings.EMAIL_FROM_NAME, smtp_user))
        msg["To"] = formataddr((to_name, to_email)) if to_name else to_email

        def _send_sync():
            """
            同步发送函数 — 在线程池中执行。

            使用 server.sendmail() 而非 send_message() 的原因：
            - send_message() 自动从 msg['From'] 提取 MAIL FROM 地址。
            - 如果 msg['From'] 包含中文显示名（如 "智能助手 <user@qq.com>"），
              QQ 邮箱会拒绝此地址格式。
            - sendmail(from_addr, to_addrs, msg) 允许我们显式指定
              纯邮箱地址作为 SMTP 层的 MAIL FROM。
            """
            try:
                context = ssl.create_default_context() if settings.EMAIL_SMTP_USE_SSL else None

                if settings.EMAIL_SMTP_USE_SSL:
                    # SSL 模式（端口 465，如 QQ 邮箱）
                    with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context) as server:
                        server.login(smtp_user, smtp_password)
                        # 使用 sendmail 显式指定纯邮箱地址作为发件人
                        server.sendmail(smtp_user, [to_email], msg.as_string())
                else:
                    # STARTTLS 模式（端口 587，先建立非加密连接再升级）
                    with smtplib.SMTP(smtp_host, smtp_port) as server:
                        server.ehlo()
                        server.starttls()  # 升级为加密连接
                        server.login(smtp_user, smtp_password)
                        server.sendmail(smtp_user, [to_email], msg.as_string())

                return True
            except Exception as e:
                raise e

        try:
            # 在线程池中执行同步 SMTP 操作（不阻塞事件循环）
            await asyncio.get_event_loop().run_in_executor(None, _send_sync)

            logger.info("email_sent_successfully", to_email=to_email)
            return f"邮件已成功发送至 {to_email}，主题：「{subject}」"

        except smtplib.SMTPAuthenticationError:
            return "SMTP 认证失败。请检查邮箱授权码是否正确。"
        except Exception as e:
            logger.error("email_smtp_failed", error=str(e), to_email=to_email)
            return f"邮件发送失败（SMTP错误）: {str(e)}"


# ============================================================================
# 导出工具实例
# ============================================================================

# Agent 通过 all_tools_map["email_assistant"] 获取这两个工具
prepare_email_tool = PrepareEmailTool()
send_email_tool = SendEmailTool()
