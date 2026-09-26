"""工时推导测试（Task 11 v1.1 验收）。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from generator.hours import HoursRules, derive, unavailable_records
from shared.config import MemberConfig
from shared.models import HOURS_EMPTY, HOURS_OK, HOURS_UNAVAILABLE, CommitRecord

MEMBERS = [
    MemberConfig(name="红豆", github_username="wsh-dotcommer", github_emails=("hongdou@example.com",)),
    MemberConfig(name="张三", github_username="zhangsan"),
]
RULES = HoursRules()
TZ = "Asia/Shanghai"
DAY = datetime(2026, 9, 18, 0, 0, tzinfo=timezone.utc)  # 2026-09-18 08:00 +08:00
WINDOW = (
    datetime(2026, 9, 17, 16, 0, tzinfo=timezone.utc),  # 2026-09-18 00:00 +08:00
    datetime(2026, 9, 18, 16, 0, tzinfo=timezone.utc),  # 2026-09-19 00:00 +08:00
)


def commit_at(moment: datetime, author: str = "wsh-dotcommer") -> CommitRecord:
    return CommitRecord(
        author=author,
        message="feat: 示例",
        timestamp=moment,
        repo="octo/demo",
        additions=1,
        deletions=0,
        files_changed=1,
    )


def local(hour: int, minute: int = 0, *, day: int = 18) -> datetime:
    """构造 +08:00 当地时间的提交时刻，返回 UTC 时间戳。"""

    moment = datetime(2026, 9, day, hour, minute, tzinfo=timezone(timedelta(hours=8)))
    return moment.astimezone(timezone.utc)


def hours_of(records: dict, username: str = "wsh-dotcommer"):
    return records[username]


def test_single_commit_counts_wrap_up() -> None:
    records = derive(MEMBERS, [commit_at(local(10))], WINDOW, TZ, RULES)

    record = hours_of(records)
    assert record.state == HOURS_OK
    assert record.hours == 0.5
    assert record.session_count == 1
    assert record.commit_count == 1


@pytest.mark.parametrize(
    ("gap_minutes", "expected_hours", "expected_sessions"),
    [
        (59, 1.5, 1),  # 同一段：59 分钟跨度 + 0.5h 收尾 = 1.48h → 1.5h
        (60, 1.5, 1),  # 等于阈值不切分
        (61, 1.0, 2),  # 超过阈值切分：两段各 0.5h
    ],
)
def test_gap_boundary(gap_minutes: int, expected_hours: float, expected_sessions: int) -> None:
    moments = [local(10), local(10) + timedelta(minutes=gap_minutes)]
    records = derive(MEMBERS, [commit_at(item) for item in moments], WINDOW, TZ, RULES)

    record = hours_of(records)
    assert record.hours == expected_hours
    assert record.session_count == expected_sessions
    assert record.commit_count == 2


def test_rounds_to_grid() -> None:
    # 20 分钟跨度 + 0.5h 收尾 = 0.83h → 收敛到 1.0h
    moments = [local(10), local(10, 20)]
    records = derive(MEMBERS, [commit_at(item) for item in moments], WINDOW, TZ, RULES)

    assert hours_of(records).hours == 1.0


def test_multiple_sessions_are_summed() -> None:
    moments = [local(9), local(9, 30), local(14), local(14, 45)]
    records = derive(MEMBERS, [commit_at(item) for item in moments], WINDOW, TZ, RULES)

    record = hours_of(records)
    assert record.session_count == 2
    # 第一段：30min + 0.5h = 1.0h；第二段：45min + 0.5h = 1.25h → 1.5h
    assert record.hours == 2.5


def test_daily_cap_is_applied() -> None:
    # 每 60 分钟一次提交、连续 13 次：单段跨度 12h + 0.5h 收尾 = 12.5h → 被上限截断
    moments = [local(9) + timedelta(minutes=60 * index) for index in range(13)]
    records = derive(MEMBERS, [commit_at(item) for item in moments], WINDOW, TZ, RULES)

    record = hours_of(records)
    assert record.session_count == 1
    assert record.hours == RULES.daily_cap_hours


def test_same_session_split_by_calendar_day() -> None:
    # 当地 23:50 与次日 00:10 只差 20 分钟，但属于两个自然日 → 两段各 0.5h
    moments = [local(23, 50, day=18), local(0, 10, day=19)]
    window = (
        datetime(2026, 9, 18, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 19, 16, 0, tzinfo=timezone.utc),
    )
    records = derive(MEMBERS, [commit_at(item) for item in moments], window, TZ, RULES)

    record = hours_of(records)
    assert record.session_count == 2
    assert record.hours == 1.0


def test_timezone_decides_the_day() -> None:
    # UTC 9/18 15:00 = 当地 9/18 23:00；UTC 9/18 17:00 = 当地 9/19 01:00 → 分属两天
    moments = [
        datetime(2026, 9, 18, 15, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 18, 17, 0, tzinfo=timezone.utc),
    ]
    window = (
        datetime(2026, 9, 18, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 19, 16, 0, tzinfo=timezone.utc),
    )
    records = derive(MEMBERS, [commit_at(item) for item in moments], window, TZ, RULES)

    assert hours_of(records).hours == 1.0


def test_commits_outside_window_are_ignored() -> None:
    inside = commit_at(local(10))
    outside = commit_at(local(10, day=17))
    records = derive(MEMBERS, [inside, outside], WINDOW, TZ, RULES)

    record = hours_of(records)
    assert record.commit_count == 1
    assert record.hours == 0.5


def test_member_without_commits_is_empty() -> None:
    records = derive(MEMBERS, [commit_at(local(10))], WINDOW, TZ, RULES)

    record = hours_of(records, "zhangsan")
    assert record.state == HOURS_EMPTY
    assert record.hours == 0.0
    assert record.detail


def test_email_identity_and_unmapped_commits() -> None:
    commits = [
        commit_at(local(10), author="hongdou@example.com"),
        commit_at(local(11), author="someone-else"),
    ]
    records = derive(MEMBERS, commits, WINDOW, TZ, RULES)

    assert hours_of(records).commit_count == 1  # 邮箱命中成员映射
    assert hours_of(records, "zhangsan").state == HOURS_EMPTY  # 未映射作者不归属任何人


def test_extra_member_from_include_others_is_counted() -> None:
    members = [*MEMBERS, MemberConfig(name="dhyabi2", github_username="dhyabi2")]
    commits = [commit_at(local(10), author="dhyabi2")]
    records = derive(members, commits, WINDOW, TZ, RULES)

    assert hours_of(records, "dhyabi2").hours == 0.5


def test_unavailable_records_cover_every_member() -> None:
    records = unavailable_records(MEMBERS, "GitHub API 超时")

    assert set(records) == {"wsh-dotcommer", "zhangsan"}
    for record in records.values():
        assert record.state == HOURS_UNAVAILABLE
        assert record.available is False
        assert record.detail == "GitHub API 超时"
