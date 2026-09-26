"""日报生成测试（Task 6 验收）。"""

from __future__ import annotations

from datetime import date, datetime, timezone

from generator import formatter
from generator.hours import HoursRules
from shared.config import MemberConfig
from shared.models import (
    SOURCE_COMMIT,
    SOURCE_DISCUSSION,
    SOURCE_ISSUE,
    CommitRecord,
    MessageRecord,
    SourceStatus,
    TaskRecord,
)

MEMBERS = [
    MemberConfig(name="红豆", github_username="wsh-dotcommer", github_emails=("hongdou@example.com",)),
    MemberConfig(name="张三", github_username="zhangsan"),
]

COMMITS = [
    CommitRecord(
        author="hongdou@example.com",
        message="feat: 新增静态日报站",
        timestamp=datetime(2026, 9, 18, 10, 0, tzinfo=timezone.utc),
        repo="octo/demo",
        additions=120,
        deletions=3,
        files_changed=4,
    )
]
TASKS = [
    TaskRecord(
        assignee="wsh-dotcommer",
        title="补齐集成测试",
        status_from="进行中",
        status_to="已完成",
        updated_at=datetime(2026, 9, 18, 11, 0, tzinfo=timezone.utc),
    )
]
MESSAGES = [
    MessageRecord(
        sender="wsh-dotcommer",
        content="<script>alert(1)</script> 这里建议补测试",
        timestamp=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        source="octo/demo PR #7",
    )
]
STATUSES = [
    SourceStatus(name=SOURCE_COMMIT, ok=True, count=1),
    SourceStatus(name=SOURCE_ISSUE, ok=True, count=1),
    SourceStatus(name=SOURCE_DISCUSSION, ok=False, count=0, error="GitHub API 超时"),
]
STATUSES_OK = [
    SourceStatus(name=SOURCE_COMMIT, ok=True, count=1),
    SourceStatus(name=SOURCE_ISSUE, ok=True, count=1),
    SourceStatus(name=SOURCE_DISCUSSION, ok=True, count=1),
]


def _report():
    return formatter.generate(date(2026, 9, 18), MEMBERS, COMMITS, TASKS, MESSAGES, STATUSES, "测试团队")


def test_markdown_contains_three_sections() -> None:
    report = _report()
    markdown = report.markdown

    assert markdown.startswith("# 智能日报 · 2026-09-18")
    assert "## 红豆（wsh-dotcommer）" in markdown
    assert "## 张三（zhangsan）" in markdown
    assert "### 代码提交" in markdown
    assert "### 任务进展" in markdown
    assert "### 工时统计" in markdown
    assert "### 协作沟通" in markdown
    assert "feat: 新增静态日报站（+120/-3，4 个文件）" in markdown
    assert "补齐集成测试：进行中 → 已完成" in markdown
    assert "代码提交 1 条" in markdown
    assert "协作沟通 数据获取失败" in markdown


def test_hours_section_order_and_content() -> None:
    markdown = _report().markdown

    # 布局顺序照书里 v1.1 的要求：任务进展 → 工时统计 → 协作沟通
    assert markdown.index("### 任务进展") < markdown.index("### 工时统计") < markdown.index("### 协作沟通")
    assert "- 工时：0.5h（1 条提交，1 个工作段）" in markdown
    assert "- 工时：团队合计 0.5h · 人均 0.25h（按提交时间推导，非真实考勤）" in markdown


def test_hours_empty_state() -> None:
    markdown = _report().markdown
    zhang_section = markdown.split("## 张三（zhangsan）", 1)[1]

    assert "- 0h（今日无记录）" in zhang_section


def test_hours_unavailable_when_commit_source_fails() -> None:
    statuses = [
        SourceStatus(name=SOURCE_COMMIT, ok=False, count=0, error="GitHub API 超时"),
        SourceStatus(name=SOURCE_ISSUE, ok=True, count=1),
        SourceStatus(name=SOURCE_DISCUSSION, ok=True, count=1),
    ]
    report = formatter.generate(date(2026, 9, 18), MEMBERS, [], TASKS, MESSAGES, statuses, "测试团队")

    assert "工时数据不可用（GitHub API 超时）" in report.markdown
    assert "工时数据不可用（GitHub API 超时）" in report.html
    assert "- 工时：团队合计 0h · 人均 0h" in report.markdown


def test_hours_can_be_disabled() -> None:
    report = formatter.generate(
        date(2026, 9, 18),
        MEMBERS,
        COMMITS,
        TASKS,
        MESSAGES,
        STATUSES,
        "测试团队",
        hours_rules=HoursRules(enabled=False),
    )

    assert "工时统计" not in report.markdown
    assert report.members[0].work_hours is None


def test_html_contains_hours_block() -> None:
    html = _report().html

    assert "<h3>工时统计</h3>" in html
    assert "按提交时间推导，非真实考勤" in html


def test_empty_member_sections_show_placeholder() -> None:
    markdown = _report().markdown
    zhang_section = markdown.split("## 张三（zhangsan）", 1)[1]

    assert zhang_section.count("- 今日无记录") == 2  # 代码提交与任务进展为空；协作沟通为失败
    assert "- 数据获取失败（GitHub API 超时）" in zhang_section


def test_html_is_escaped_and_renders_sections() -> None:
    report = formatter.generate(date(2026, 9, 18), MEMBERS, COMMITS, TASKS, MESSAGES, STATUSES_OK, "测试团队")
    html = report.html

    assert "<h3>代码提交</h3>" in html
    assert "<h3>任务进展</h3>" in html
    assert "<h3>协作沟通</h3>" in html
    assert "&lt;script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert "octo/demo PR #7" in html


def test_unmapped_identity_detection() -> None:
    extra = CommitRecord(
        author="unknown-user",
        message="chore: 未知作者",
        timestamp=datetime(2026, 9, 18, 13, 0, tzinfo=timezone.utc),
        repo="octo/demo",
        additions=1,
        deletions=0,
        files_changed=1,
    )
    assert formatter.find_unmapped(MEMBERS, [*COMMITS, extra], TASKS, MESSAGES) == {"unknown-user"}


def test_content_preview_truncates_long_message() -> None:
    long_text = "feat " + "很长的讨论内容" * 40
    messages = [
        MessageRecord(
            sender="wsh-dotcommer",
            content=long_text,
            timestamp=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
            source="octo/demo PR #7",
        )
    ]
    report = formatter.generate(date(2026, 9, 18), MEMBERS, [], [], messages, STATUSES_OK, "测试团队")

    assert "…" in report.markdown
    assert long_text not in report.markdown
