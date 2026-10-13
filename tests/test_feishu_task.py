"""飞书任务状态采集测试（v2.4 验收）：三态映射、翻页、降级与只读边界。"""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from collector import feishu_message, feishu_task
from shared.config import FeishuSourceConfig, FeishuTaskConfig
from shared.errors import CollectorError
from shared.http import TOKEN_PATH
from shared.models import STATUS_DONE, STATUS_IN_PROGRESS, STATUS_NOT_STARTED
from tests.conftest import json_response

TASKS_PATH = "/open-apis/task/v2/tasks"
SECRET_TEXT = "任务描述里的机密内容"

PAST = 1590000000  # 2020-05-21，一定早于"现在"
FUTURE = 2524608000  # 2050-01-01，一定晚于"现在"
DUE = 1790000000


def _task(
    guid: str,
    summary: str,
    *,
    completed_at: int = 0,
    start: int | None = None,
    due: int | None = None,
    updated_at: int | None = None,
) -> dict:
    """飞书任务 v2 的最小字段集：时间一律是秒级时间戳字符串。"""

    payload: dict = {
        "guid": guid,
        "summary": summary,
        "completed_at": str(completed_at),
        "description": SECRET_TEXT,
    }
    if start is not None:
        payload["start"] = {"timestamp": str(start), "is_all_day": False}
    if due is not None:
        payload["due"] = {"timestamp": str(due), "is_all_day": False}
    if updated_at is not None:
        payload["updated_at"] = str(updated_at)
    return payload


TASKS = [
    _task("t-done", "已经做完的事", completed_at=PAST, due=DUE, updated_at=PAST),
    _task("t-doing", "正在做的事", start=PAST, due=DUE, updated_at=PAST),
    _task("t-todo", "还没开始的事", start=FUTURE),
    _task("t-nostart", "没填开始时间的事"),
]


@pytest.fixture
def task_config(config):
    return replace(
        config,
        sources=replace(
            config.sources,
            feishu=FeishuSourceConfig(
                enabled=False,
                app_id="cli_demo",
                app_secret="app-secret",
                tasks=FeishuTaskConfig(enabled=True),
            ),
        ),
    )


def _handler(
    seen: list[str],
    *,
    page_size: int = 2,
    token_status: int = 200,
    tasks: list[dict] | None = None,
):
    payload = TASKS if tasks is None else tasks

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == TOKEN_PATH:
            return json_response({"code": 0, "tenant_access_token": "t-demo"})
        if request.url.path.startswith("/open-apis/task/v2/tasks") or "/tasklists/" in request.url.path:
            if token_status != 200:
                return httpx.Response(
                    token_status,
                    json={
                        "code": 99991672,
                        "msg": "Access denied. One of the following scopes is required: "
                        "[task:task:read, task:task:write]",
                    },
                )
            page = int(request.url.params.get("page_token") or 0)
            chunk = payload[page * page_size : (page + 1) * page_size]
            return json_response(
                {
                    "code": 0,
                    "data": {
                        "items": chunk,
                        "has_more": (page + 1) * page_size < len(payload),
                        "page_token": str(page + 1),
                    },
                }
            )
        return httpx.Response(404, json={"code": 1, "msg": "not found"})

    return handler


def _patch(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    monkeypatch.setattr(
        feishu_message,
        "build_client",
        lambda _config: feishu_message.FeishuClient(
            "cli_demo",
            "app-secret",
            transport=httpx.MockTransport(handler),
            sleep=lambda _seconds: None,
        ),
    )


def test_collect_maps_three_states(task_config, monkeypatch) -> None:
    _patch(monkeypatch, _handler([]))

    tasks = feishu_task.collect(task_config)

    by_guid = {item.guid: item for item in tasks}
    assert by_guid["t-done"].status == STATUS_DONE
    assert by_guid["t-doing"].status == STATUS_IN_PROGRESS
    assert by_guid["t-todo"].status == STATUS_NOT_STARTED
    # 飞书没返回 start 字段时退化为"未完成即进行中"
    assert by_guid["t-nostart"].status == STATUS_IN_PROGRESS


def test_collect_parses_due_and_updated_at(task_config, monkeypatch) -> None:
    _patch(monkeypatch, _handler([]))

    by_guid = {item.guid: item for item in feishu_task.collect(task_config)}

    assert by_guid["t-done"].due is not None
    assert by_guid["t-done"].due.isoformat() == "2026-09-21"
    assert by_guid["t-done"].updated_at is not None
    assert by_guid["t-todo"].due is None
    assert by_guid["t-todo"].updated_at is None


def test_collect_never_keeps_task_description(task_config, monkeypatch) -> None:
    _patch(monkeypatch, _handler([]))

    tasks = feishu_task.collect(task_config)

    assert SECRET_TEXT not in repr(tasks)
    assert not hasattr(tasks[0], "description")


def test_collect_follows_page_token(task_config, monkeypatch) -> None:
    seen: list[str] = []
    _patch(monkeypatch, _handler(seen, page_size=2))

    tasks = feishu_task.collect(task_config)

    assert len(tasks) == len(TASKS)
    assert seen.count(TASKS_PATH) == 2  # 4 条 / 每页 2 条


def test_disabled_source_returns_empty_without_requests(task_config, monkeypatch) -> None:
    seen: list[str] = []
    _patch(monkeypatch, _handler(seen))
    disabled = replace(
        task_config,
        sources=replace(
            task_config.sources,
            feishu=replace(task_config.sources.feishu, tasks=FeishuTaskConfig(enabled=False)),
        ),
    )

    assert feishu_task.collect(disabled) == []
    assert seen == []  # 一条请求都不发


def test_tasklist_scope_uses_tasklist_path(task_config, monkeypatch) -> None:
    seen: list[str] = []
    _patch(monkeypatch, _handler(seen))
    scoped = replace(
        task_config,
        sources=replace(
            task_config.sources,
            feishu=replace(
                task_config.sources.feishu,
                tasks=FeishuTaskConfig(enabled=True, scope="tasklist", tasklist_guids=("f8b3",)),
            ),
        ),
    )

    tasks = feishu_task.collect(scoped)

    assert len(tasks) == len(TASKS)
    assert "/open-apis/task/v2/tasklists/f8b3/tasks" in seen
    assert TASKS_PATH not in seen


def test_max_tasks_truncates(task_config, monkeypatch) -> None:
    _patch(monkeypatch, _handler([], page_size=2))
    limited = replace(
        task_config,
        sources=replace(
            task_config.sources,
            feishu=replace(
                task_config.sources.feishu,
                tasks=FeishuTaskConfig(enabled=True, max_tasks=3),
            ),
        ),
    )

    assert len(feishu_task.collect(limited)) == 3


def test_permission_error_is_translated_to_actionable_hint(task_config, monkeypatch) -> None:
    _patch(monkeypatch, _handler([], token_status=400))

    with pytest.raises(CollectorError) as excinfo:
        feishu_task.collect(task_config)

    message = str(excinfo.value)
    assert "task:task:read" in message
    assert "重新发布" in message
    assert "99991672" in message


def test_server_error_degrades_to_collector_error(task_config, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == TOKEN_PATH:
            return json_response({"code": 0, "tenant_access_token": "t-demo"})
        return httpx.Response(500, json={"code": 1, "msg": "boom"})

    _patch(monkeypatch, handler)

    with pytest.raises(CollectorError):
        feishu_task.collect(task_config)


def test_items_missing_guid_are_dropped(task_config, monkeypatch) -> None:
    _patch(monkeypatch, _handler([], tasks=[{"summary": "没有 guid"}, *_task_list()]))

    tasks = feishu_task.collect(task_config)

    assert len(tasks) == 1
    assert tasks[0].guid == "t-done"


def _task_list() -> list[dict]:
    return [_task("t-done", "唯一有效的一条", completed_at=PAST)]
