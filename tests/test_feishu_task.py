"""飞书任务状态采集测试（v2.4 验收）：三态映射、翻页、降级与只读边界。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from collector import feishu_task
from shared.feishu_oauth import UserToken, UserTokenStore, UserTokenProvider
from shared.http import FeishuClient
from shared.config import FeishuSourceConfig, FeishuTaskConfig
from shared.errors import CollectorError
from shared.http import TOKEN_PATH
from shared.models import STATUS_DONE, STATUS_IN_PROGRESS, STATUS_NOT_STARTED, FeishuTaskRecord
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
    """注入 Mock 客户端；未配用户令牌提供者 → 走应用身份，行为与 v2.4 一致。"""

    monkeypatch.setattr(
        feishu_task,
        "build_client",
        lambda _config: FeishuClient(
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


# ===== v2.5：用户身份（user_access_token） =====


def _with_user_token(config, tmp_path: Path):
    """把配置指向临时的令牌文件，并预置一个有效期还很长的用户令牌。"""

    token_file = tmp_path / "feishu-user-token.json"
    UserTokenStore(token_file).save(
        UserToken(
            access_token="u-user-token",
            refresh_token="ur-1",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
    )
    return replace(
        config,
        sources=replace(
            config.sources,
            feishu=replace(
                config.sources.feishu,
                tasks=replace(config.sources.feishu.tasks, user_token_file=str(token_file)),
            ),
        ),
    )


def _patch_with_user(monkeypatch: pytest.MonkeyPatch, handler, config) -> None:
    """注入带用户令牌提供者的客户端（令牌有效，不会去换 token）。"""

    provider = UserTokenProvider(
        "cli_demo",
        "app-secret",
        UserTokenStore(config.sources.feishu.tasks.user_token_file),
    )
    monkeypatch.setattr(
        feishu_task,
        "build_client",
        lambda _config: FeishuClient(
            "cli_demo",
            "app-secret",
            transport=httpx.MockTransport(handler),
            sleep=lambda _seconds: None,
            user_token_provider=provider,
        ),
    )


def test_user_identity_reads_my_tasks_and_merges_with_v2(task_config, tmp_path, monkeypatch) -> None:
    """配了用户令牌后：v2 与 v1「我负责的」都查，按 guid 去重合并。"""

    seen: list[tuple[str, str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        seen.append(
            (
                request.url.path,
                request.headers.get("Authorization", ""),
                params.get("type", ""),
            )
        )
        if request.url.path == "/open-apis/task/v2/tasks":
            return json_response(
                {"code": 0, "data": {"items": [_task("t-v2", "v2 里的任务")], "has_more": False}}
            )
        if request.url.path == "/open-apis/task/v1/tasks":
            # v1 形态：guid 是 id，完成时间字段叫 complete_time
            return json_response(
                {
                    "code": 0,
                    "data": {
                        "items": [
                            {"id": "t-v1", "summary": "v1 里的任务", "complete_time": ""},
                            {"id": "t-v2", "summary": "重复的一条", "complete_time": ""},
                        ],
                        "has_more": False,
                    },
                }
            )
        return httpx.Response(404, json={"code": 1, "msg": "not found"})

    user_config = _with_user_token(task_config, tmp_path)
    _patch_with_user(monkeypatch, handler, user_config)

    tasks = feishu_task.collect(user_config)

    assert {item.guid for item in tasks} == {"t-v2", "t-v1"}  # 重复的 t-v2 被去掉
    assert all(auth == "Bearer u-user-token" for _, auth, _ in seen)  # 全程用用户身份
    assert ("/open-apis/task/v1/tasks", "Bearer u-user-token", "my_tasks") in seen


def test_user_identity_maps_v1_complete_time_to_done(task_config, tmp_path, monkeypatch) -> None:
    """v1 的 complete_time 非空 → 已完成；v1 没有开始时间，不会出现「未开始」。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/open-apis/task/v1/tasks":
            return json_response(
                {
                    "code": 0,
                    "data": {
                        "items": [
                            {"id": "t-done", "summary": "做完的", "complete_time": str(PAST)},
                            {"id": "t-open", "summary": "没做完的", "complete_time": ""},
                        ],
                        "has_more": False,
                    },
                }
            )
        return json_response({"code": 0, "data": {"items": [], "has_more": False}})

    user_config = _with_user_token(task_config, tmp_path)
    _patch_with_user(monkeypatch, handler, user_config)

    by_guid = {item.guid: item for item in feishu_task.collect(user_config)}

    assert by_guid["t-done"].status == STATUS_DONE
    assert by_guid["t-open"].status == STATUS_IN_PROGRESS


# ===== v2.5.2：隐藏「基准时间之前完成」的任务 =====

CST = timezone(timedelta(hours=8))
BASELINE = datetime(2026, 10, 14, 0, 0, tzinfo=CST)  # 日报目标日 00:00
WINDOW_END = datetime(2026, 10, 14, 18, 0, tzinfo=CST)


def _seconds(moment: datetime) -> int:
    return int(moment.timestamp())


def test_collect_hides_tasks_completed_before_baseline(task_config, monkeypatch) -> None:
    items = [
        _task("t-old", "昨天完成的", completed_at=_seconds(datetime(2026, 10, 13, 10, 0, tzinfo=CST))),
        _task("t-today", "今天完成的", completed_at=_seconds(datetime(2026, 10, 14, 10, 0, tzinfo=CST))),
        _task("t-doing", "进行中的"),
        _task("t-todo", "还没开始的", start=_seconds(datetime(2026, 10, 20, 9, 0, tzinfo=CST))),
    ]
    _patch(monkeypatch, _handler([], page_size=50, tasks=items))

    tasks = feishu_task.collect(task_config, BASELINE, WINDOW_END)

    # 未完成的（进行中/未开始）全留；已完成只留"当天完成"的
    assert {item.guid for item in tasks} == {"t-today", "t-doing", "t-todo"}


def test_completed_exactly_at_baseline_is_kept(task_config, monkeypatch) -> None:
    """边界：完成时间正好等于基准（00:00:00）时保留，按 >= 处理。"""

    _patch(monkeypatch, _handler([], page_size=50, tasks=[_task("t-edge", "卡在零点整", completed_at=_seconds(BASELINE))]))

    assert [item.guid for item in feishu_task.collect(task_config, BASELINE, WINDOW_END)] == ["t-edge"]


def test_collect_without_window_keeps_everything(task_config, monkeypatch) -> None:
    """没传采集窗口时不过滤——fail-open，行为与 v2.4 一致。"""

    items = [_task("t-old", "很久以前完成的", completed_at=_seconds(datetime(2020, 5, 21, tzinfo=CST)))]
    _patch(monkeypatch, _handler([], page_size=50, tasks=items))

    assert [item.guid for item in feishu_task.collect(task_config)] == ["t-old"]


def test_hide_old_completed_keeps_done_without_timestamp() -> None:
    """已完成但缺完成时间：宁可多显示也不误伤。"""

    record = FeishuTaskRecord(guid="t-nostamp", summary="缺完成时间", status=STATUS_DONE)

    assert feishu_task._hide_old_completed([record], BASELINE) == [record]
    assert feishu_task._hide_old_completed([record], None) == [record]


def test_backfill_uses_that_day_as_baseline(task_config, monkeypatch) -> None:
    """补跑历史日期时基准跟着那天走：11 号完成的任务在 11 号那期里要出现。"""

    items = [
        _task("t-11", "11 号完成的", completed_at=_seconds(datetime(2026, 10, 11, 20, 0, tzinfo=CST))),
        _task("t-10", "10 号完成的", completed_at=_seconds(datetime(2026, 10, 10, 20, 0, tzinfo=CST))),
    ]
    _patch(monkeypatch, _handler([], page_size=50, tasks=items))

    backfilled = feishu_task.collect(
        task_config,
        datetime(2026, 10, 11, 0, 0, tzinfo=CST),
        datetime(2026, 10, 12, 0, 0, tzinfo=CST),
    )

    assert [item.guid for item in backfilled] == ["t-11"]


def test_no_user_token_falls_back_to_app_identity(task_config, monkeypatch) -> None:
    """本地还没授权时，不会去调 v1「我负责的」，行为与 v2.4 一致。"""

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == TOKEN_PATH:
            return json_response({"code": 0, "tenant_access_token": "t-tenant"})
        return json_response({"code": 0, "data": {"items": [], "has_more": False}})

    provider = UserTokenProvider(
        "cli_demo", "app-secret", UserTokenStore(Path("data/definitely-missing-token.json"))
    )
    monkeypatch.setattr(
        feishu_task,
        "build_client",
        lambda _config: FeishuClient(
            "cli_demo",
            "app-secret",
            transport=httpx.MockTransport(handler),
            sleep=lambda _seconds: None,
            user_token_provider=provider,
        ),
    )

    assert feishu_task.collect(task_config) == []
    assert "/open-apis/task/v1/tasks" not in seen
