"""飞书工作台任务状态采集（v2.4，只读）。

接口契约：
    collect(config, start=None, end=None) -> list[FeishuTaskRecord]

与 `feishu_message` 的区别：群消息是"某个时间窗内发生了什么"（带窗口），
任务是"此刻是什么状态"（无窗口，取快照），因此这里的 start/end 只为兼容
采集计划里统一的调用签名，不参与过滤。

只读边界：只读取任务标题、状态、截止时间；不写库、不改飞书数据、
不把任务描述（description）带进任何模型或产物。
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from collector import feishu_message
from shared.config import Config, FeishuTaskConfig
from shared.errors import CollectorError
from shared.http import FeishuClient
from shared.logger import JsonLineLogger, build_logger
from shared.models import (
    STATUS_DONE,
    STATUS_IN_PROGRESS,
    STATUS_NOT_STARTED,
    FeishuTaskRecord,
)

TASKS_PATH = "/open-apis/task/v2/tasks"
TASKLIST_TASKS_PATH = "/open-apis/task/v2/tasklists/{guid}/tasks"
PAGE_SIZE = 100
MAX_PAGES = 20

# 权限错误的官方错误码：单独翻译成可执行的提示，避免把原始报文塞进日报
PERMISSION_ERROR_CODE = "99991672"
PERMISSION_HINT = (
    "飞书任务接口未授权：请在开发者后台为该应用添加 task:task:read 与 "
    "task:tasklist:read 权限并重新发布版本"
)


def collect(
    config: Config,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[FeishuTaskRecord]:
    """拉取飞书任务的当前状态快照；未启用时直接返回空列表、不发任何请求。"""

    tasks_config = config.sources.feishu.tasks
    if not tasks_config.enabled:
        return []

    logger = build_logger(config.report.log_path, echo=False)
    now = datetime.now(timezone.utc)
    records: list[FeishuTaskRecord] = []
    try:
        with feishu_message.build_client(config) as client:
            for raw in _fetch(client, tasks_config, logger):
                record = _map_task(raw, now)
                if record is not None:
                    records.append(record)
    except CollectorError as exc:
        if PERMISSION_ERROR_CODE in str(exc):
            raise CollectorError(f"{PERMISSION_HINT}（错误码 {PERMISSION_ERROR_CODE}）") from exc
        raise

    logger.info(
        "feishu_tasks_collected",
        total=len(records),
        done=sum(1 for item in records if item.status == STATUS_DONE),
        in_progress=sum(1 for item in records if item.status == STATUS_IN_PROGRESS),
        not_started=sum(1 for item in records if item.status == STATUS_NOT_STARTED),
        scope=tasks_config.scope,
    )
    return records


def _fetch(
    client: FeishuClient,
    tasks_config: FeishuTaskConfig,
    logger: JsonLineLogger,
) -> list[dict]:
    """按配置的同步范围翻页取任务；超出 max_tasks 时截断并记日志。"""

    if tasks_config.scope == "tasklist":
        paths = [TASKLIST_TASKS_PATH.format(guid=guid) for guid in tasks_config.tasklist_guids]
    else:
        paths = [TASKS_PATH]

    items: list[dict] = []
    for path in paths:
        items.extend(_paginate(client, path, tasks_config.max_tasks - len(items)))
        if len(items) >= tasks_config.max_tasks:
            logger.error(
                "feishu_tasks_truncated",
                limit=tasks_config.max_tasks,
                path=path,
            )
            break
    return items[: tasks_config.max_tasks]


def _paginate(client: FeishuClient, path: str, budget: int) -> list[dict]:
    items: list[dict] = []
    page_token = ""
    pages = 0
    while pages < MAX_PAGES and len(items) < budget:
        params = {"page_size": min(PAGE_SIZE, max(budget - len(items), 1))}
        if page_token:
            params["page_token"] = page_token
        data = client.get_json(path, params) or {}
        pages += 1
        batch = data.get("items") or []
        if not isinstance(batch, list):
            raise CollectorError(f"飞书任务返回的 items 不是列表: {path}")
        items.extend(item for item in batch if isinstance(item, dict))
        page_token = str(data.get("page_token") or "")
        if not data.get("has_more") or not page_token:
            break
    return items


def _map_task(raw: dict, now: datetime) -> FeishuTaskRecord | None:
    """把飞书任务对象映射成模型；缺 guid 的条目直接丢弃。"""

    guid = str(raw.get("guid") or "").strip()
    if not guid:
        return None
    return FeishuTaskRecord(
        guid=guid,
        summary=str(raw.get("summary") or "").strip() or "(无标题)",
        status=resolve_status(raw, now),
        due=_to_date(raw.get("due")),
        updated_at=_to_moment(raw.get("updated_at")),
        url=str(raw.get("url") or "").strip(),
    )


def resolve_status(raw: dict, now: datetime) -> str:
    """三态映射（design.md §4.2）：已完成 → 未开始 → 进行中。

    - 已完成：`completed_at` 非空且不是 `0`（飞书用 "0" 表示未完成）
    - 未开始：未完成，且配置了开始时间且该时间还在未来
    - 进行中：其余未完成任务；飞书未返回 `start` 字段时一律归入此类
    """

    if _to_moment(raw.get("completed_at")) is not None:
        return STATUS_DONE
    start = _to_moment(raw.get("start"))
    if start is not None and start > now:
        return STATUS_NOT_STARTED
    return STATUS_IN_PROGRESS


def _to_moment(value: object) -> datetime | None:
    """飞书时间字段是秒级 Unix 时间戳字符串；`0`/空/非法一律视为没有值。"""

    if isinstance(value, dict):
        value = value.get("timestamp")
    raw = str(value if value is not None else "").strip()
    if not raw.isdigit():
        return None
    seconds = int(raw)
    if seconds <= 0:
        return None
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def _to_date(value: object) -> date | None:
    moment = _to_moment(value)
    return moment.date() if moment is not None else None
