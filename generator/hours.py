"""工时推导（design.md §4.2、§6.4，Task 11 v1.1）。

接口契约：
    derive(members, commits, window, timezone_name, rules) -> dict[str, WorkHoursRecord]

纯本地计算：不访问网络、不读写文件，同一组提交必然得到同一结果。
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
) -> dict[str, WorkHoursRecord]:
    """按会话法推导每位成员的工时，返回 {成员 GitHub 用户名(小写): 工时记录}。"""

    member_list = list(members)
    timezone = ZoneInfo(timezone_name)
    records: dict[str, WorkHoursRecord] = {}

    # 先按 (成员, 自然日) 归组窗口内的提交
    grouped: dict[str, dict[object, list[datetime]]] = {_key(member): {} for member in member_list}
    for commit in commits:
        if not (window[0] <= commit.timestamp < window[1]):
            continue
        member = _owner(member_list, commit.author)
        if member is None:
            continue
        local_moment = commit.timestamp.astimezone(timezone)
        grouped[_key(member)].setdefault(local_moment.date(), []).append(local_moment)

    for member in member_list:
        moments_by_day = grouped[_key(member)]
        if not moments_by_day:
            records[_key(member)] = WorkHoursRecord(state=HOURS_EMPTY, detail=EMPTY_DETAIL)
            continue

        total_hours = 0.0
        session_count = 0
        commit_count = 0
        for _, moments in sorted(moments_by_day.items(), key=lambda item: item[0]):
            sessions = _split_sessions(sorted(moments), rules)
            day_hours = sum(_session_hours(session, rules) for session in sessions)
            day_hours = min(day_hours, rules.daily_cap_hours)
            day_hours = _round_to_grid(day_hours, rules.rounding_hours)
            total_hours += day_hours
            session_count += len(sessions)
            commit_count += len(moments)

        records[_key(member)] = WorkHoursRecord(
            hours=round(total_hours, 2),
            session_count=session_count,
            commit_count=commit_count,
            state=HOURS_OK,
            detail=f"{commit_count} 条提交，{session_count} 个工作段",
        )
    return records


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
