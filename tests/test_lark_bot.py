"""飞书机器人推送测试（Task 8 验收）。"""

from __future__ import annotations

from datetime import date, datetime, timezone

import httpx

from notifier import lark_bot
from shared.models import DailyReport, MemberReport


def _report(markdown: str = "# 智能日报\n\n### 代码提交\n- feat: 示例") -> DailyReport:
    return DailyReport(
        date=date(2026, 9, 18),
        team_name="测试团队",
        members=[MemberReport(name="红豆", github_username="wsh-dotcommer")],
        generated_at=datetime(2026, 9, 18, 18, 0, tzinfo=timezone.utc),
        markdown=markdown,
        html="<h1>智能日报</h1>",
    )


TARGET = lark_bot.LarkBotTarget(webhook="https://open.feishu.cn/open-apis/bot/v2/hook/test")


def test_send_posts_markdown_card() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = request.read().decode("utf-8")
        return httpx.Response(200, json={"code": 0, "msg": "success"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        ok = lark_bot.send(_report(), TARGET, client=client)

    assert ok is True
    assert '"msg_type": "interactive"' in captured["payload"] or '"msg_type":"interactive"' in captured["payload"]
    assert "lark_md" in captured["payload"]
    assert "### 代码提交" in captured["payload"]


def test_send_retries_twice_then_returns_false() -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(200, json={"code": 19001, "msg": "param error"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        ok = lark_bot.send(_report(), TARGET, client=client)

    assert ok is False
    assert len(attempts) == 3


def test_payload_truncates_long_markdown() -> None:
    payload = lark_bot.build_payload(_report(markdown="x" * 9000))
    content = payload["card"]["elements"][0]["text"]["content"]

    assert len(content) <= lark_bot.MAX_MARKDOWN_LENGTH + 20
    assert "已截断" in content
    assert payload["card"]["header"]["title"]["content"] == "测试团队 · 2026-09-18 智能日报"
