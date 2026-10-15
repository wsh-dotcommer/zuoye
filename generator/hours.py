"""工时推导（design.md §4.2、§6.4，Task 11 v1.1）。

接口契约：
    derive(members, commits, window, timezone_name, rules, *, tasks=(), messages=())
        -> dict[str, WorkHoursRecord]

纯本地计算：不访问网络、不读写文件，同一组提交必然得到同一结果。

v2.7：口径从"只按提交时间"扩到"按活动时间"——提交、Issue 状态变更、评论
三条时间线合并成一条活动流，再交给同一套会话法。`tasks`/`messages` 是仅
关键字参数且默认空，因此旧调用行为不变。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

from shared.config import HoursConfig, MemberConfig
from shared.models import (
    HOURS_EMPTY,
    HOURS_OK,
    HOURS_UNAVAILABLE,
    CommitRecord,
    MessageRecord,
    TaskRecord,
    WorkHoursRecord,
)

EMPTY_DETAIL = "今日无记录"


@dataclass(frozen=True)
class HoursRules:
    """会话法参数（与配置 hours 块一一对应）。"""

    enabled: bool = True
    gap_minutes: int = 60
    wrap_up_hours: float = 0.5
    rounding_hours: float = 0.5
    daily_cap_hours: float = 12.0

    @classmethod
    def from_config(cls, config: HoursConfig) -> HoursRules:
        return cls(
            enabled=config.enabled,
            gap_minutes=config.gap_minutes,
            wrap_up_hours=config.wrap_up_hours,
            rounding_hours=config.rounding_hours,
            daily_cap_hours=config.daily_cap_hours,
        )


def derive(
    members: Iterable[MemberConfig],
    commits: Sequence[CommitRecord],
    window: tuple[datetime, datetime],
    timezone_name: str,
    rules: HoursRules,
    *,
    tasks: Sequence[TaskRecord] = (),
    messages: Sequence[MessageRecord] = (),
) -> dict[str, WorkHoursRecord]:
    """按会话法推导每位成员的工时，返回 {成员 GitHub 用户名(小写): 工时记录}。

    活动三类：提交（`author`）、任务状态变更（`assignee`，用变更发生的那一刻）、
    评论（`sender`）。三类按采集窗口左闭右开过滤，未匹配到成员的身份不计入。
    """

    member_list = list(members)
    timezone = ZoneInfo(timezone_name)
    records: dict[str, WorkHoursRecord] = {}

    # 先按 (成员, 自然日) 归组窗口内的活动
    grouped: dict[str, dict[object, list[datetime]]] = {_key(member): {} for member in member_list}
    counts: dict[str, list[int]] = {_key(member): [0, 0, 0] for member in member_list}  # 提交/任务/评论

    def record_activity(identity: str, moment: datetime, kind: int) -> None:
        if not (window[0] <= moment < window[1]):
            return
        member = _owner(member_list, identity)
        if member is None:
            return
        local_moment = moment.astimezone(timezone)
        grouped[_key(member)].setdefault(local_moment.date(), []).append(local_moment)
        counts[_key(member)][kind] += 1

    for commit in commits:
        record_activity(commit.author, commit.timestamp, 0)
    for task in tasks:
        record_activity(task.assignee, task.updated_at, 1)
    for message in messages:
        record_activity(message.sender, message.timestamp, 2)

    for member in member_list:
        moments_by_day = grouped[_key(member)]
        if not moments_by_day:
            records[_key(member)] = WorkHoursRecord(state=HOURS_EMPTY, detail=EMPTY_DETAIL)
            continue

        total_hours = 0.0
        session_count = 0
        activity_count = 0
        for _, moments in sorted(moments_by_day.items(), key=lambda item: item[0]):
            sessions = _split_sessions(sorted(moments), rules)
            day_hours = sum(_session_hours(session, rules) for session in sessions)
            day_hours = min(day_hours, rules.daily_cap_hours)
            day_hours = _round_to_grid(day_hours, rules.rounding_hours)
            total_hours += day_hours
            session_count += len(sessions)
            activity_count += len(moments)

        commits_n, tasks_n, comments_n = counts[_key(member)]
        records[_key(member)] = WorkHoursRecord(
            hours=round(total_hours, 2),
            session_count=session_count,
            commit_count=commits_n,
            task_count=tasks_n,
            comment_count=comments_n,
            state=HOURS_OK,
            detail=_build_detail(
                commit_count=commits_n,
                task_count=tasks_n,
                comment_count=comments_n,
                session_count=session_count,
                activity_count=activity_count,
            ),
        )
    return records


def _build_detail(
    *,
    commit_count: int,
    task_count: int,
    comment_count: int,
    session_count: int,
    activity_count: int,
) -> str:
    """工时行的括号补充：只列非零类别，避免出现"任务 0"这种噪音。"""

    parts: list[str] = []
    if commit_count:
        parts.append(f"提交 {commit_count}")
    if task_count:
        parts.append(f"任务 {task_count}")
    if comment_count:
        parts.append(f"评论 {comment_count}")
    if not parts:
        # 理论上进不来（有活动才有此行），留个兜底避免出现空括号
        parts.append(f"{activity_count} 条活动")
    return " · ".join(parts) + f"，{session_count} 个工作段"


def unavailable_records(
    members: Iterable[MemberConfig],
    reason: str,
) -> dict[str, WorkHoursRecord]:
    """提交数据源失败时，全员工时统一标记为不可用（design.md §4.2）。"""

    return {
        _key(member): WorkHoursRecord(state=HOURS_UNAVAILABLE, detail=reason or "未知原因")
        for member in members
    }


def _split_sessions(moments: Sequence[datetime], rules: HoursRules) -> list[list[datetime]]:
    """相邻提交间隔超过阈值就切分为新的工作段；等于阈值不切分。"""

    sessions: list[list[datetime]] = []
    for moment in moments:
        if not sessions:
            sessions.append([moment])
            continue
        gap = moment - sessions[-1][-1]
        if gap > timedelta(minutes=rules.gap_minutes):
            sessions.append([moment])
        else:
            sessions[-1].append(moment)
    return sessions


def _session_hours(session: Sequence[datetime], rules: HoursRules) -> float:
    """一段的时长 = 末次 − 首次 + 收尾；孤提交的段只算收尾。"""

    span_hours = (session[-1] - session[0]).total_seconds() / 3600
    return span_hours + rules.wrap_up_hours


def _round_to_grid(value: float, grid: float) -> float:
    """按网格四舍五入（半值向上，符合规范里的"四舍五入"口径）。"""

    steps = (Decimal(str(value)) / Decimal(str(grid))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return float(steps * Decimal(str(grid)))


def _key(member: MemberConfig) -> str:
    return member.github_username.strip().lower()


def _owner(members: Sequence[MemberConfig], identity: str) -> MemberConfig | None:
    for member in members:
        if member.matches(identity):
            return member
    return None
