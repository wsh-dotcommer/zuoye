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

from shared.config import Config, FeishuTaskConfig
from shared.errors import CollectorError
from shared.feishu_oauth import UserTokenProvider, UserTokenStore
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
# 用户身份专用：v1 的「我负责的」列表（应用身份查这个永远是空）
MY_TASKS_PATH = "/open-apis/task/v1/tasks"
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
        with build_client(config) as client:
            as_user = client.user_token_configured
            logger.info("feishu_tasks_identity", as_user=as_user)
            for raw in _fetch(client, tasks_config, logger, as_user=as_user):
                record = _map_task(raw, now)
                if record is not None:
                    records.append(record)
    except CollectorError as exc:
        if PERMISSION_ERROR_CODE in str(exc):
            raise CollectorError(f"{PERMISSION_HINT}（错误码 {PERMISSION_ERROR_CODE}）") from exc
        raise

    raw_total = len(records)
    records = _hide_old_completed(records, start)
    hidden = raw_total - len(records)
    if hidden:
        logger.info(
            "feishu_tasks_filtered",
            hidden=hidden,
            baseline=start.isoformat() if start else "",
            reason="completed_before_baseline",
        )

    logger.info(
        "feishu_tasks_collected",
        total=len(records),
        done=sum(1 for item in records if item.status == STATUS_DONE),
        in_progress=sum(1 for item in records if item.status == STATUS_IN_PROGRESS),
        not_started=sum(1 for item in records if item.status == STATUS_NOT_STARTED),
        scope=tasks_config.scope,
    )
    return records


def _hide_old_completed(
    records: list[FeishuTaskRecord],
    baseline: datetime | None,
) -> list[FeishuTaskRecord]:
    """隐藏"基准时间之前完成"的任务（v2.5.2）。

    留什么：未完成的全部留下（进行中 / 未开始，含逾期未完成），以及**基准之后完成**的。
    基准 = 采集窗口起点，普通运行就是"日报目标日 00:00"（配置时区），补跑历史日期时
    自动变成那一天 00:00。`baseline` 为空（没传窗口）或任务缺完成时间时**不过滤**，
    宁可多显示也不误伤。
    """

    if baseline is None:
        return records
    return [
        record
        for record in records
        if not (
            record.status == STATUS_DONE
            and record.completed_at is not None
            and record.completed_at < baseline
        )
    ]


def build_client(config: Config) -> FeishuClient:
    """构造任务读取用的飞书客户端（测试通过替换本函数注入 Mock）。

    配置了 `use_user_token` 时会带上用户令牌提供者；本地还没有授权文件时
    `user_token_configured` 为假，采集器自动退回应用身份（行为与 v2.4 相同）。
    """

    feishu = config.sources.feishu
    tasks_config = feishu.tasks
    provider: UserTokenProvider | None = None
    if tasks_config.use_user_token:
        provider = UserTokenProvider(
            feishu.app_id,
            feishu.app_secret,
            UserTokenStore(tasks_config.user_token_file),
            base_url=feishu.base_url,
        )
    return FeishuClient(
        feishu.app_id,
        feishu.app_secret,
        base_url=feishu.base_url,
        retry_times=feishu.retry_times,
        timeout=feishu.timeout_seconds,
        logger=build_logger(config.report.log_path, echo=False),
        user_token_provider=provider,
    )


def _fetch(
    client: FeishuClient,
    tasks_config: FeishuTaskConfig,
    logger: JsonLineLogger,
    *,
    as_user: bool = False,
) -> list[dict]:
    """按配置的同步范围翻页取任务；超出 max_tasks 时截断并记日志。"""

    if tasks_config.scope == "tasklist":
        paths = [TASKLIST_TASKS_PATH.format(guid=guid) for guid in tasks_config.tasklist_guids]
    else:
        paths = [TASKS_PATH]

    items: list[dict] = []
    for path in paths:
        items.extend(
            _paginate(client, path, tasks_config.max_tasks - len(items), as_user=as_user)
        )
        if len(items) >= tasks_config.max_tasks:
            logger.error(
                "feishu_tasks_truncated",
                limit=tasks_config.max_tasks,
                path=path,
            )
            break

    # 用户身份下再补一次 v1 的「我负责的」：v1 与 v2 是两个任务空间，
    # 同名任务可能只在其中一边出现，按 guid 去重后合并。
    if as_user and tasks_config.scope == "all" and len(items) < tasks_config.max_tasks:
        extra = _paginate(
            client,
            MY_TASKS_PATH,
            tasks_config.max_tasks - len(items),
            as_user=True,
            params={"type": "my_tasks"},
        )
        seen = {str(item.get("guid") or item.get("id") or "") for item in items}
        items.extend(item for item in extra if _task_key(item) not in seen)
    return items[: tasks_config.max_tasks]


def _task_key(item: dict) -> str:
    return str(item.get("guid") or item.get("id") or "")


def _paginate(
    client: FeishuClient,
    path: str,
    budget: int,
    *,
    as_user: bool = False,
    params: dict | None = None,
) -> list[dict]:
    items: list[dict] = []
    page_token = ""
    pages = 0
    while pages < MAX_PAGES and len(items) < budget:
        query = dict(params or {})
        query["page_size"] = min(PAGE_SIZE, max(budget - len(items), 1))
        if page_token:
            query["page_token"] = page_token
        data = client.get_json(path, query, as_user=as_user) or {}
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
    """把飞书任务对象映射成模型；缺 guid/id 的条目直接丢弃。

    兼容两种返回形态：v2 用 `guid`/`completed_at`/`start`，v1 用
    `id`/`complete_time`（时间戳是毫秒级）。
    """

    guid = _task_key(raw).strip()
    if not guid:
        return None
    return FeishuTaskRecord(
        guid=guid,
        summary=str(raw.get("summary") or "").strip() or "(无标题)",
        status=resolve_status(raw, now),
        due=_to_date(raw.get("due")),
        completed_at=_to_moment(raw.get("completed_at") or raw.get("complete_time")),
        updated_at=_to_moment(raw.get("updated_at") or raw.get("modify_time")),
        url=str(raw.get("url") or "").strip(),
    )


def resolve_status(raw: dict, now: datetime) -> str:
    """三态映射（design.md §4.2）：已完成 → 未开始 → 进行中。

    - 已完成：`completed_at` 非空且不是 `0`（飞书用 "0" 表示未完成）
    - 未开始：未完成，且配置了开始时间且该时间还在未来
    - 进行中：其余未完成任务；飞书未返回 `start` 字段时一律归入此类
      （v1 的任务对象没有开始时间字段，因此 v1 只会出现"已完成/进行中"）
    """

    if _to_moment(raw.get("completed_at") or raw.get("complete_time")) is not None:
        return STATUS_DONE
    start = _to_moment(raw.get("start"))
    if start is not None and start > now:
        return STATUS_NOT_STARTED
    return STATUS_IN_PROGRESS


def _to_moment(value: object) -> datetime | None:
    """飞书时间字段是 Unix 时间戳字符串；`0`/空/非法一律视为没有值。

    v2 用秒级（10 位）、v1 用毫秒级（13 位），按位数自动判别；`due` 这类
    对象里秒级键叫 `timestamp`、毫秒级键叫 `time`，两种都认。
    """

    if isinstance(value, dict):
        value = value.get("timestamp", value.get("time"))
    raw = str(value if value is not None else "").strip()
    if not raw.isdigit():
        return None
    digits = int(raw)
    if digits <= 0:
        return None
    if digits >= 10**12:  # 13 位及以上视为毫秒
        return datetime.fromtimestamp(digits / 1000, tz=timezone.utc)
    return datetime.fromtimestamp(digits, tz=timezone.utc)


def _to_date(value: object) -> date | None:
    moment = _to_moment(value)
    return moment.date() if moment is not None else None
