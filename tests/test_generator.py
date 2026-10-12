"""日报生成测试（Task 6 验收）。"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone

from generator import formatter
from generator.hours import HoursRules
from shared.config import MemberConfig
from shared.models import (
    SOURCE_COMMIT,
    SOURCE_DISCUSSION,
    SOURCE_ISSUE,
    ChatSummaryRecord,
    CommitRecord,
    MessageRecord,
    ReportStats,
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
        files=("a.py", "b.py", "c.py", "d.py"),
        sha="abc1234def",
        url="https://github.com/octo/demo/commit/abc1234def",
    )
]
TASKS = [
    TaskRecord(
        assignee="wsh-dotcommer",
        title="补齐集成测试",
        status_from="进行中",
        status_to="已完成",
        updated_at=datetime(2026, 9, 18, 11, 0, tzinfo=timezone.utc),
        number=7,
        url="https://github.com/octo/demo/issues/7",
        labels=("日报",),
        comment_count=2,
    )
]
MESSAGES = [
    MessageRecord(
        sender="wsh-dotcommer",
        content="<script>alert(1)</script> 这里建议补测试",
        timestamp=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        source="octo/demo PR #7",
        url="https://github.com/octo/demo/pull/7#discussion_r1",
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

    assert markdown.startswith("# 测试团队 智能日报 · 2026-09-18")
    # HTML 侧（邮件正文与站点页共用）的标题也要带团队名
    assert "<h1>测试团队 智能日报 · 2026-09-18</h1>" in report.html
    assert "<title>测试团队 智能日报 · 2026-09-18</title>" in report.html
    assert "## 红豆（wsh-dotcommer）" in markdown
    assert "## 张三（zhangsan）" in markdown
    assert "### 代码提交" in markdown
    assert "### 任务进展" in markdown
    assert "### 工时统计" in markdown
    assert "### 协作沟通" in markdown
    assert "feat: 新增静态日报站（+120/-3，4 个文件：a.py、b.py、c.py、d.py）" in markdown
    assert "补齐集成测试：进行中 → 已完成" in markdown
    assert "代码提交 1 条" in markdown
    assert "协作沟通 数据获取失败" in markdown
    assert "- `octo/demo` [abc1234](https://github.com/octo/demo/commit/abc1234def) " in markdown
    assert "- [#7](https://github.com/octo/demo/issues/7) 补齐集成测试：进行中 → 已完成（标签：日报 · 2 条评论）" in markdown
    assert "指派：" not in markdown  # 指派人与本段成员一致时不重复写名字


def test_message_source_is_linked_when_discussion_available() -> None:
    markdown = formatter.generate(
        date(2026, 9, 18), MEMBERS, COMMITS, TASKS, MESSAGES, STATUSES_OK, "测试团队"
    ).markdown

    assert (
        "- [octo/demo PR #7](https://github.com/octo/demo/pull/7#discussion_r1) wsh-dotcommer："
        in markdown
    )


def test_html_renders_inline_links_as_anchors() -> None:
    html = _report().html

    assert '<a href="https://github.com/octo/demo/issues/7" target="_blank" rel="noopener">#7</a>' in html
    assert '<a href="https://github.com/octo/demo/commit/abc1234def" target="_blank" rel="noopener">abc1234</a>' in html
    assert "[#7]" not in html  # 方括号标记不该残留在 HTML 里


def test_header_shows_comparison_and_trend_when_history_exists() -> None:
    report = formatter.generate(
        date(2026, 9, 18),
        MEMBERS,
        COMMITS,
        TASKS,
        MESSAGES,
        STATUSES_OK,
        "测试团队",
        recent=[ReportStats(date=date(2026, 9, 17))],
    )

    assert "- 对比上期（2026-09-17）：提交 +1 · 任务 +1 · 沟通 +1 · 工时 +0.5h" in report.markdown
    assert "- 近 2 期：提交 ▁█（1 条） · 工时 ▁█（0.5h）" in report.markdown
    assert "head-lines" in report.html  # HTML 版与 Markdown 用同一份 view


def test_header_hides_comparison_and_trend_without_history() -> None:
    markdown = _report().markdown

    assert "对比上期" not in markdown
    assert "期：提交" not in markdown  # 只有当期一个点，趋势行不出现


def test_sparkline_edge_cases() -> None:
    assert formatter._sparkline([]) == ""
    assert formatter._sparkline([0, 0]) == "▁▁"  # 全 0 统一最低档，不虚高
    assert formatter._sparkline([5]) == "█"
    assert formatter._sparkline([0, 2]) == "▁█"
    assert formatter._sparkline([1, 2, 4]) == "▃▅█"


def test_delta_text_formats_sign_zero_and_hours() -> None:
    assert formatter._delta_text(0) == "±0"
    assert formatter._delta_text(0, unit="h") == "±0h"
    assert formatter._delta_text(-2) == "-2"
    assert formatter._delta_text(0.5, unit="h") == "+0.5h"


def test_chat_summaries_render_team_level_line() -> None:
    report = formatter.generate(
        date(2026, 9, 18),
        MEMBERS,
        COMMITS,
        TASKS,
        MESSAGES,
        STATUSES,
        "测试团队",
        chat_summaries=(
            ChatSummaryRecord(chat_name="智能日报", message_count=12, speaker_count=3),
            ChatSummaryRecord(chat_name="研发群", message_count=4, speaker_count=2),
        ),
    )

    assert "- 飞书群：智能日报 12 条 · 3 人发言；研发群 4 条 · 2 人发言" in report.markdown
    assert report.chat_message_count == 16


def test_single_member_merges_team_line_and_skips_member_heading() -> None:
    single = [MEMBERS[0]]
    report = formatter.generate(
        date(2026, 9, 18), single, COMMITS, TASKS, MESSAGES, STATUSES, "测试团队"
    )

    assert "- 团队：测试团队（@wsh-dotcommer）" in report.markdown
    assert "\n## " not in report.markdown  # 单人时不再重复成员标题
    assert "### 代码提交" in report.markdown
    assert 'class="panel-heading"' not in report.html
    assert "<h2>" not in report.html


def test_two_members_keep_member_headings() -> None:
    report = _report()

    assert "- 团队：测试团队\n" in report.markdown
    assert "- 团队：测试团队（@" not in report.markdown
    assert "## 红豆（wsh-dotcommer）" in report.markdown
    assert 'class="panel-heading"' in report.html


def test_commit_files_are_truncated_to_limit() -> None:
    files = tuple(f"file-{index}.py" for index in range(11))
    commits = [replace(COMMITS[0], files=files, files_changed=len(files))]

    markdown = formatter.generate(
        date(2026, 9, 18), MEMBERS, commits, TASKS, MESSAGES, STATUSES, "测试团队"
    ).markdown

    assert "（+120/-3，11 个文件：file-0.py、" in markdown
    assert "file-9.py、…）" in markdown
    assert "file-10.py" not in markdown  # 第 11 个被截断


def test_commit_without_file_names_keeps_count_only_format() -> None:
    commits = [replace(COMMITS[0], files=())]

    markdown = formatter.generate(
        date(2026, 9, 18), MEMBERS, commits, TASKS, MESSAGES, STATUSES, "测试团队"
    ).markdown

    assert "feat: 新增静态日报站（+120/-3，4 个文件）" in markdown
    assert "个文件：" not in markdown  # 没有文件名时不留空冒号


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
