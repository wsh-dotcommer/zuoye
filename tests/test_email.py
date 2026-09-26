"""邮件推送测试（Task 7 验收）。"""

from __future__ import annotations

import smtplib
from datetime import date, datetime, timezone

from notifier import email as email_notifier
from shared.models import DailyReport, MemberReport


def _report() -> DailyReport:
    return DailyReport(
        date=date(2026, 9, 18),
        team_name="测试团队",
        members=[MemberReport(name="红豆", github_username="wsh-dotcommer")],
        generated_at=datetime(2026, 9, 18, 18, 0, tzinfo=timezone.utc),
        markdown="# 智能日报 · 2026-09-18",
        html="<h1>智能日报 · 2026-09-18</h1>",
    )


TARGET = email_notifier.EmailTarget(
    host="smtp.example.com",
    port=465,
    use_ssl=True,
    sender="bot@example.com",
    username="bot@example.com",
    password="secret",
    recipients=("leader@example.com",),
)


class _FakeSmtp:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.logged_in = False
        self.sent: list = []

    def __enter__(self) -> _FakeSmtp:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def login(self, username: str, password: str) -> None:
        self.logged_in = True

    def send_message(self, message) -> None:
        if self.fail:
            raise smtplib.SMTPException("发送失败")
        self.sent.append(message)


def test_send_builds_html_message() -> None:
    fake = _FakeSmtp()
    ok = email_notifier.send(
        _report(),
        TARGET,
        smtp_factory=lambda _target: fake,
        logger=None,
    )

    assert ok is True
    assert fake.logged_in is True
    message = fake.sent[0]
    assert message["Subject"] == "[测试团队] 2026-09-18 智能日报"
    assert message["To"] == "leader@example.com"
    assert message.get_content_type() == "multipart/alternative"
    html_part = message.get_payload()[1]
    assert html_part.get_content_type() == "text/html"


def test_send_retries_twice_then_returns_false() -> None:
    attempts: list[int] = []

    def factory(_target):
        attempts.append(1)
        return _FakeSmtp(fail=True)

    ok = email_notifier.send(_report(), TARGET, smtp_factory=factory)

    assert ok is False
    assert len(attempts) == 3  # 首次 + 重试 2 次


def test_check_does_not_send() -> None:
    fake = _FakeSmtp()
    ok, detail = email_notifier.check(TARGET, smtp_factory=lambda _target: fake)

    assert ok is True
    assert fake.sent == []
    assert "SMTP" in detail
