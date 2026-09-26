"""飞书机器人推送测试（Task 8 验收）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
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


def test_payload_without_secret_has_no_signature() -> None:
    """v1.1 行为必须保持：没配 secret 时不带 timestamp / sign。"""

    payload = lark_bot.build_payload(_report())

    assert "timestamp" not in payload
    assert "sign" not in payload


def test_gen_sign_matches_official_algorithm() -> None:
    timestamp = 1700000000
    secret = "demo-secret"
    expected = base64.b64encode(
        hmac.new(f"{timestamp}\n{secret}".encode("utf-8"), digestmod=hashlib.sha256).digest()
    ).decode("utf-8")

    assert lark_bot.gen_sign(timestamp, secret) == expected


def test_send_with_secret_posts_timestamp_and_sign() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = request.read().decode("utf-8")
        return httpx.Response(200, json={"code": 0, "msg": "success"})

    target = lark_bot.LarkBotTarget(webhook=TARGET.webhook, secret="demo-secret")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        ok = lark_bot.send(_report(), target, client=client)

    assert ok is True
    assert '"timestamp"' in captured["payload"]
    assert '"sign"' in captured["payload"]


def test_check_sends_plain_text_message() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = request.read().decode("utf-8")
        return httpx.Response(200, json={"code": 0, "msg": "success"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        ok, detail = lark_bot.check(TARGET, client=client)

    assert ok is True
    assert "连通性正常" in detail
    assert '"msg_type": "text"' in captured["payload"] or '"msg_type":"text"' in captured["payload"]
    assert "连通性自检" in captured["payload"]


def test_check_signs_payload_when_secret_configured() -> None:
    """v1.2 回归：自检消息同样要走签名，否则启用签名校验的机器人会返回 19021。"""

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = request.read().decode("utf-8")
        return httpx.Response(200, json={"code": 0, "msg": "success"})

    target = lark_bot.LarkBotTarget(webhook=TARGET.webhook, secret="demo-secret")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        ok, _ = lark_bot.check(target, client=client)

    assert ok is True
    assert '"timestamp"' in captured["payload"]
    assert '"sign"' in captured["payload"]


def test_check_reports_failure_without_retrying() -> None:
    attempts: list[int] = []
    logs: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(200, json={"code": 19021, "msg": "sign match fail"})

    logger = _collecting_logger(logs)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        ok, detail = lark_bot.check(TARGET, client=client, logger=logger)

    assert ok is False
    assert len(attempts) == 1
    assert "自检失败" in detail
    assert logs[-1]["hint"] == lark_bot.SIGN_FAILED_HINT


def _collecting_logger(sink: list[dict]):
    class _Logger:
        def info(self, event: str, **fields) -> None:
            sink.append({"level": "INFO", "event": event, **fields})

        def error(self, event: str, **fields) -> None:
            sink.append({"level": "ERROR", "event": event, **fields})

    return _Logger()
