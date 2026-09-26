"""GitHub Issue 采集测试（Task 4 验收）。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import httpx

from collector import github_issue
from shared.models import STATUS_DONE, STATUS_IN_PROGRESS, STATUS_NEW
from tests.conftest import issue_item, json_response, patch_client

START = datetime(2026, 9, 17, 16, 0, tzinfo=timezone.utc)
END = datetime(2026, 9, 18, 16, 0, tzinfo=timezone.utc)

ISSUES = [
    issue_item(
        1,
        "新增日报模板",
        created_at="2026-09-18T01:00:00Z",
        updated_at="2026-09-18T01:00:00Z",
        assignee="wsh-dotcommer",
    ),
    issue_item(
        2,
        "修复限流等待",
        state="closed",
        created_at="2026-09-10T01:00:00Z",
        updated_at="2026-09-18T05:00:00Z",
        closed_at="2026-09-18T05:00:00Z",
        assignee="zhangsan",
    ),
    issue_item(
        3,
        "重新打开的任务",
        created_at="2026-09-01T01:00:00Z",
        updated_at="2026-09-18T06:00:00Z",
        assignee="wsh-dotcommer",
    ),
    issue_item(
        4,
        "只改了标签",
        created_at="2026-08-01T01:00:00Z",
        updated_at="2026-09-18T07:00:00Z",
        assignee="wsh-dotcommer",
    ),
    issue_item(
        5,
        "这是一个 PR",
        created_at="2026-09-18T02:00:00Z",
        updated_at="2026-09-18T02:00:00Z",
        pull_request=True,
    ),
]

TIMELINES = {
    1: [],
    2: [{"event": "closed", "created_at": "2026-09-18T05:00:00Z"}],
    3: [{"event": "reopened", "created_at": "2026-09-18T06:00:00Z"}],
    4: [{"event": "labeled", "created_at": "2026-09-18T07:00:00Z"}],
}


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/issues"):
        return json_response(ISSUES)
    if "/issues/" in path and path.endswith("/timeline"):
        number = int(path.split("/issues/")[1].split("/")[0])
        return json_response(TIMELINES.get(number, []))
    return httpx.Response(404, json={"message": "not found"})


def test_collect_maps_issue_state_changes(config, monkeypatch) -> None:
    patch_client(monkeypatch, github_issue, _handler)

    records = github_issue.collect(config, START, END)

    by_title = {record.title: record for record in records}
    assert len(records) == 3  # #4（仅标签变化）与 #5（PR）被剔除
    assert by_title["新增日报模板"].status_from == STATUS_NEW
    assert by_title["新增日报模板"].status_to == STATUS_IN_PROGRESS
    assert by_title["修复限流等待"].status_from == STATUS_IN_PROGRESS
    assert by_title["修复限流等待"].status_to == STATUS_DONE
    assert by_title["重新打开的任务"].status_from == STATUS_DONE
    assert by_title["重新打开的任务"].status_to == STATUS_IN_PROGRESS
    assert by_title["修复限流等待"].assignee == "zhangsan"
    assert by_title["修复限流等待"].updated_at == datetime(2026, 9, 18, 5, 0, tzinfo=timezone.utc)
    assert all(record.title and record.assignee for record in records)


def test_collect_falls_back_when_timeline_unavailable(config, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/issues"):
            return json_response(ISSUES)
        return httpx.Response(500, json={"message": "timeline down"})

    patch_client(monkeypatch, github_issue, handler, retry_times=1)

    records = github_issue.collect(config, START, END)

    by_title = {record.title: record for record in records}
    assert by_title["修复限流等待"].status_to == STATUS_DONE  # 由 closed_at 兜底推断
    assert by_title["新增日报模板"].status_from == STATUS_NEW
    assert "只改了标签" not in by_title


def test_collect_respects_timeline_budget(config, monkeypatch) -> None:
    """timeline 预算耗尽后必须退化到字段推断，而不是无限请求。"""

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/issues"):
            return json_response(ISSUES)
        calls.append(path)
        return json_response(TIMELINES.get(int(path.split("/issues/")[1].split("/")[0]), []))

    limited = replace(
        config,
        sources=replace(config.sources, github=replace(config.sources.github, max_issue_timelines=1)),
    )
    patch_client(monkeypatch, github_issue, handler)

    records = github_issue.collect(limited, START, END)

    assert len(calls) == 1  # 只允许查询一次 timeline
    by_title = {record.title: record for record in records}
    assert by_title["修复限流等待"].status_to == STATUS_DONE  # 由 closed_at 兜底推断


def test_unassigned_issue_falls_back_to_actor(config, monkeypatch) -> None:
    """未分配负责人时，用状态变更执行者（或创建者）作为归属人。"""

    issues = [
        issue_item(
            8,
            "未分配但已关闭的任务",
            state="closed",
            created_at="2026-09-10T01:00:00Z",
            updated_at="2026-09-18T09:00:00Z",
            closed_at="2026-09-18T09:00:00Z",
        ),
    ]
    issues[0]["user"] = {"login": "issue-author"}
    issues[0]["closed_by"] = {"login": "issue-closer"}
    timelines = {8: [{"event": "closed", "created_at": "2026-09-18T09:00:00Z", "actor": {"login": "issue-closer"}}]}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/issues"):
            return json_response(issues)
        number = int(path.split("/issues/")[1].split("/")[0])
        return json_response(timelines.get(number, []))

    patch_client(monkeypatch, github_issue, handler)

    records = github_issue.collect(config, START, END)

    assert [record.assignee for record in records] == ["issue-closer"]
