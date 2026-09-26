"""GitHub 提交采集测试（Task 3 验收）。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import httpx
import pytest

from collector import github_commit
from shared.errors import CollectorError
from tests.conftest import commit_detail, commit_item, json_response, patch_client

START = datetime(2026, 9, 17, 16, 0, tzinfo=timezone.utc)  # 2026-09-18 00:00 +08:00
END = datetime(2026, 9, 18, 16, 0, tzinfo=timezone.utc)


def _commits_payload() -> list[dict]:
    return [
        commit_item("sha-a", "wsh-dotcommer", "hongdou@example.com", "2026-09-18T10:00:00Z"),
        commit_item("sha-b", None, "hongdou@example.com", "2026-09-18T11:00:00Z", "fix: 修复配置校验"),
        commit_item("sha-c", "zhangsan", "zhangsan@example.com", "2026-09-18T20:00:00Z"),
    ]


def _handler(seen: list[str], *, stats_status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/commits"):
            assert request.url.params.get("per_page") == "100"
            return json_response(_commits_payload())
        if "/commits/sha-" in request.url.path:
            if stats_status != 200:
                return httpx.Response(stats_status, json={"message": "boom"})
            return json_response(commit_detail(120, 3, 4))
        return httpx.Response(404, json={"message": "not found"})

    return handler


def test_collect_returns_seven_fields(config, monkeypatch) -> None:
    seen: list[str] = []
    patch_client(monkeypatch, github_commit, _handler(seen))

    records = github_commit.collect(config, START, END)

    assert len(records) == 2  # sha-c 超出采集窗口，被剔除
    first = records[0]
    assert first.author == "wsh-dotcommer"
    assert first.message == "feat: 示例提交"
    assert first.repo == "octo/demo"
    assert isinstance(first.additions, int)
    assert isinstance(first.deletions, int)
    assert isinstance(first.files_changed, int)
    assert first.timestamp == datetime(2026, 9, 18, 10, 0, tzinfo=timezone.utc)
    assert (first.additions, first.deletions, first.files_changed) == (120, 3, 4)


def test_collect_falls_back_to_email_when_login_missing(config, monkeypatch) -> None:
    patch_client(monkeypatch, github_commit, _handler([]))

    records = github_commit.collect(config, START, END)

    assert records[1].author == "hongdou@example.com"
    assert records[1].message == "fix: 修复配置校验"


def test_collect_respects_details_limit(config, monkeypatch) -> None:
    seen: list[str] = []
    patch_client(monkeypatch, github_commit, _handler(seen))

    limited = replace(
        config,
        sources=replace(config.sources, github=replace(config.sources.github, max_commit_details=1)),
    )

    records = github_commit.collect(limited, START, END)

    detail_calls = [path for path in seen if "/commits/sha-" in path]
    assert len(detail_calls) == 1
    assert (records[1].additions, records[1].deletions, records[1].files_changed) == (0, 0, 0)


def test_collect_keeps_record_when_stats_unavailable(config, monkeypatch) -> None:
    patch_client(monkeypatch, github_commit, _handler([], stats_status=500), retry_times=1)

    records = github_commit.collect(config, START, END)

    assert len(records) == 2
    assert records[0].files_changed == 0


def test_collect_raises_collector_error_on_failure(config, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "server error"})

    patch_client(monkeypatch, github_commit, handler, retry_times=1)

    with pytest.raises(CollectorError):
        github_commit.collect(config, START, END)


def test_empty_repository_is_treated_as_no_commits(config, monkeypatch) -> None:
    """空仓库（HTTP 409）应计 0 条，而不是标记数据源失败。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"message": "Git Repository is empty."})

    patch_client(monkeypatch, github_commit, handler, retry_times=1)

    assert github_commit.collect(config, START, END) == []


def test_bot_commits_are_excluded(config, monkeypatch) -> None:
    payload = [
        commit_item("sha-bot", "dependabot[bot]", "bot@example.com", "2026-09-18T09:00:00Z", "chore: 依赖升级"),
        commit_item("sha-human", "wsh-dotcommer", "hongdou@example.com", "2026-09-18T10:00:00Z"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/commits"):
            return json_response(payload)
        return json_response(commit_detail(1, 1, 1))

    patch_client(monkeypatch, github_commit, handler)

    records = github_commit.collect(config, START, END)

    assert [record.author for record in records] == ["wsh-dotcommer"]
