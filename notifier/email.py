"""邮件推送（design.md §4.4，Task 7）。

接口契约：
    send(report, target) -> bool
"""

from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Callable, ContextManager

from shared.errors import NotifierError
from shared.logger import JsonLineLogger, build_logger
from shared.models import DailyReport

RETRY_TIMES = 2
SMTP_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class EmailTarget:
    """一封邮件需要的全部投递参数（凭据由编排层从环境变量解析后注入）。"""

    host: str
    port: int
    use_ssl: bool
    sender: str
    username: str
    password: str
    recipients: tuple[str, ...]


SmtpFactory = Callable[[EmailTarget], ContextManager[smtplib.SMTP]]


def send(
    report: DailyReport,
    target: EmailTarget,
    *,
    smtp_factory: SmtpFactory | None = None,
    retry_times: int = RETRY_TIMES,
    logger: JsonLineLogger | None = None,
) -> bool:
    """通过 SMTP 发送 HTML 日报，失败重试 2 次后返回 False。"""

    log = logger or build_logger(None)
    message = _build_message(report, target)
    factory = smtp_factory or _default_factory
    attempts = retry_times + 1

    for attempt in range(1, attempts + 1):
        try:
            with factory(target) as smtp:
                if target.username:
                    smtp.login(target.username, target.password)
                smtp.send_message(message)
            log.info("email_sent", subject=message["Subject"], recipients=len(target.recipients))
            return True
        except (smtplib.SMTPException, OSError, NotifierError) as exc:
            log.error("email_send_failed", attempt=attempt, error=str(exc))
    return False


def _build_message(report: DailyReport, target: EmailTarget) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = f"[{report.team_name}] {report.date.isoformat()} 智能日报"
    message["From"] = target.sender
    message["To"] = ", ".join(target.recipients)
    message.set_content(report.markdown or "（日报内容为空）")
    message.add_alternative(report.html or "<p>（日报内容为空）</p>", subtype="html")
    return message


def check(
    target: EmailTarget,
    *,
    smtp_factory: SmtpFactory | None = None,
) -> tuple[bool, str]:
    """--check 模式使用：只连接（必要时登录），不发送任何邮件。"""

    factory = smtp_factory or _default_factory
    try:
        with factory(target) as smtp:
            if target.username:
                smtp.login(target.username, target.password)
        return True, "SMTP 连接与登录成功"
    except (smtplib.SMTPException, OSError) as exc:
        return False, f"SMTP 检查失败: {exc}"


def _default_factory(target: EmailTarget) -> ContextManager[smtplib.SMTP]:
    if target.use_ssl:
        return smtplib.SMTP_SSL(target.host, target.port, timeout=SMTP_TIMEOUT_SECONDS)
    return smtplib.SMTP(target.host, target.port, timeout=SMTP_TIMEOUT_SECONDS)
