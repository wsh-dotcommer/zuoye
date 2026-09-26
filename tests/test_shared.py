"""共享基础层测试（Task 2 验收）。"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest

from shared.config import Config, load_config
from shared.errors import CollectorError, ConfigError
from shared.http import GitHubClient
from shared.logger import build_logger
from shared.models import DailyReport, MemberReport
from shared.storage import Storage
from tests.conftest import config_text, json_response, make_client


def test_load_config_resolves_env_and_defaults(config: Config, tmp_path: Path) -> None:
    assert config.team.name == "测试团队"
    assert config.sources.github.token == "test-token"
    assert len(config.repos) == 1
    assert config.members[0].github_emails == ("hongdou@example.com",)
    assert config.report.site_dir == tmp_path / "docs"
    assert config.notify.email.enabled is False


def test_load_config_reports_missing_env(config_file: Path) -> None:
    loaded = load_config(config_file, env={})
    assert loaded.sources.github.token == ""
    assert "GITHUB_TOKEN" in loaded.missing_env
    # token 属可选凭据：未设置只做提示，不算致命问题
    assert loaded.required_missing_env == ()


def test_load_config_marks_required_missing_env(tmp_path: Path) -> None:
    text = config_text(tmp_path).replace(
        "  lark_bot:\n    enabled: false",
        "  lark_bot:\n    enabled: true\n    webhook: ${LARK_BOT_WEBHOOK}",
    )
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")

    loaded = load_config(path, env={"GITHUB_TOKEN": "test-token"})

    assert "LARK_BOT_WEBHOOK" in loaded.missing_env
    assert loaded.required_missing_env == ("LARK_BOT_WEBHOOK",)


def test_load_config_parses_lark_secret(tmp_path: Path) -> None:
    """v1.2：飞书机器人签名密钥从环境变量注入，未配置时为空字符串（不启用签名）。"""

    text = config_text(tmp_path).replace(
        "  lark_bot:\n    enabled: false",
        "  lark_bot:\n    enabled: true\n    webhook: ${LARK_BOT_WEBHOOK}\n    secret: ${LARK_BOT_SECRET}",
    )
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")

    loaded = load_config(
        path,
        env={"GITHUB_TOKEN": "test-token", "LARK_BOT_WEBHOOK": "https://example.com/hook", "LARK_BOT_SECRET": "s3cret"},
    )
    assert loaded.notify.lark_bot.secret == "s3cret"

    unsigned = load_config(path, env={"GITHUB_TOKEN": "test-token", "LARK_BOT_WEBHOOK": "https://example.com/hook"})
    assert unsigned.notify.lark_bot.webhook == "https://example.com/hook"
    assert unsigned.notify.lark_bot.secret == ""
    assert unsigned.required_missing_env == ()


def test_load_config_reads_dotenv_file(tmp_path: Path) -> None:
    """v1.1 修复：.env 会被自动读取（真实环境变量优先）。"""

    (tmp_path / ".env").write_text(
        "# 注释行\nSMTP_USERNAME=me@example.com\nSMTP_PASSWORD='授权码'\nexport SMTP_EXTRA=1\n",
        encoding="utf-8",
    )
    text = config_text(tmp_path).replace(
        "  email:\n    enabled: false",
        "  email:\n    enabled: true\n    host: smtp.example.com\n    sender: me@example.com\n"
        "    username: ${SMTP_USERNAME}\n    password: ${SMTP_PASSWORD}\n    recipients: [leader@example.com]",
    )
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")

    loaded = load_config(path, env=None, cwd=tmp_path)

    assert loaded.notify.email.username == "me@example.com"
    assert loaded.notify.email.password == "授权码"
    # 只有未在 .env 里提供的 GITHUB_TOKEN 算缺失；SMTP 两个值已从 .env 读到
    assert loaded.missing_env == ("GITHUB_TOKEN",)
    assert loaded.required_missing_env == ()


def test_dotenv_empty_value_is_reported_missing(tmp_path: Path) -> None:
    """占位符在 .env 里是空值时，仍应被 --check 报出来。"""

    (tmp_path / ".env").write_text("SMTP_USERNAME=me@example.com\nSMTP_PASSWORD=\n", encoding="utf-8")
    text = config_text(tmp_path).replace(
        "  email:\n    enabled: false",
        "  email:\n    enabled: true\n    host: smtp.example.com\n    sender: me@example.com\n"
        "    username: ${SMTP_USERNAME}\n    password: ${SMTP_PASSWORD}\n    recipients: [leader@example.com]",
    )
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")

    loaded = load_config(path, env=None, cwd=tmp_path)

    assert "SMTP_PASSWORD" in loaded.missing_env
    assert loaded.required_missing_env == ("SMTP_PASSWORD",)


def test_dotenv_with_bom_is_parsed(tmp_path: Path) -> None:
    """记事本保存 .env 时可能带 BOM，第一行的键不能被读坏。"""

    (tmp_path / ".env").write_bytes(
        "\ufeffSMTP_USERNAME=me@example.com\nSMTP_PASSWORD=secret\n".encode("utf-8")
    )
    text = config_text(tmp_path).replace(
        "  email:\n    enabled: false",
        "  email:\n    enabled: true\n    host: smtp.example.com\n    sender: me@example.com\n"
        "    username: ${SMTP_USERNAME}\n    password: ${SMTP_PASSWORD}\n    recipients: [leader@example.com]",
    )
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")

    loaded = load_config(path, env=None, cwd=tmp_path)

    assert loaded.notify.email.username == "me@example.com"
    assert loaded.notify.email.password == "secret"


def test_load_config_missing_required_block(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("team:\n  name: X\n", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_config(path)
    assert "repos" in str(excinfo.value)


def test_load_config_invalid_holiday(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        config_text(tmp_path).replace("skip_weekends: false", "skip_weekends: false\n  holidays: [2026/10/01]"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as excinfo:
        load_config(path)
    assert "holidays" in str(excinfo.value)


def test_load_config_enabled_email_requires_recipients(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    text = config_text(tmp_path).replace(
        "  email:\n    enabled: false",
        "  email:\n    enabled: true\n    host: smtp.example.com\n    sender: bot@example.com",
    )
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_config(path)
    assert "recipients" in str(excinfo.value)


def test_logger_writes_json_lines_and_redacts(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "test.jsonl"
    logger = build_logger(log_path, echo=False)
    logger.info("source_collected", source="github_commit", count=3)
    logger.error("source_failed", error="boom", token="secret-value")
    logger.info("discussion", content="很长的讨论内容")

    lines = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["event"] == "source_collected"
    assert lines[0]["count"] == 3
    assert lines[1]["level"] == "ERROR"
    assert lines[1]["token"] == "***"
    assert lines[2]["content"].startswith("<")


def test_storage_is_idempotent(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "data" / "reports.sqlite3")
    report = DailyReport(
        date=date(2026, 9, 18),
        team_name="测试团队",
        members=[MemberReport(name="红豆", github_username="wsh-dotcommer")],
        generated_at=datetime(2026, 9, 18, 18, 0, tzinfo=timezone.utc),
        markdown="# 第一版",
        html="<p>第一版</p>",
    )
    storage.save(report, "daily-report-2026-09-18.html")
    report.markdown = "# 第二版"
    storage.save(report, "daily-report-2026-09-18.html")

    entries = storage.list_reports()
    assert len(entries) == 1
    assert entries[0].markdown == "# 第二版"
    assert entries[0].member_count == 1
    assert storage.get(date(2026, 9, 18)).site_file == "daily-report-2026-09-18.html"
    assert storage.get(date(2026, 9, 17)) is None


def test_http_retries_on_transport_error() -> None:
    attempts: list[float] = []
    state = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["count"] += 1
        if state["count"] < 3:
            raise httpx.ConnectTimeout("超时")
        return json_response({"ok": True})

    client = make_client(handler, retry_times=3, retry_interval=5.0, sleep=attempts.append)
    assert client.get_json("/repos/octo/demo") == {"ok": True}
    assert state["count"] == 3
    assert attempts == [5.0, 5.0]


def test_http_waits_for_rate_limit_reset() -> None:
    waits: list[float] = []
    state = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["count"] += 1
        if state["count"] == 1:
            return httpx.Response(
                403,
                json={"message": "API rate limit exceeded"},
                headers={"X-RateLimit-Remaining": "0", "Retry-After": "7"},
            )
        return json_response([{"ok": 1}])

    client = make_client(handler, retry_times=3, sleep=waits.append)
    assert client.get_json("/repos/octo/demo/issues") == [{"ok": 1}]
    assert waits == [7.0]


def test_http_raises_after_retries_exhausted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "server error"})

    client = make_client(handler, retry_times=2, retry_interval=0.0)
    with pytest.raises(CollectorError) as excinfo:
        client.get_json("/repos/octo/demo")
    assert "服务端错误" in str(excinfo.value)


def test_http_client_error_is_not_retried() -> None:
    state = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["count"] += 1
        return httpx.Response(404, json={"message": "Not Found"})

    client = make_client(handler, retry_times=3)
    with pytest.raises(CollectorError) as excinfo:
        client.get_json("/repos/octo/missing")
    assert "404" in str(excinfo.value)
    assert state["count"] == 1


def test_paginate_stops_on_short_page() -> None:
    pages = {
        1: [{"id": 1}, {"id": 2}],
        2: [{"id": 3}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        return json_response(pages.get(page, []))

    client = make_client(handler)
    items = list(client.paginate("/repos/octo/demo/commits", per_page=2))
    assert [item["id"] for item in items] == [1, 2, 3]


def test_client_sends_token_header() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization", "")
        return json_response({})

    client = make_client(handler, token="abc123")
    client.get_json("/rate_limit")
    assert seen["auth"] == "Bearer abc123"
    assert client.auth_configured is True
