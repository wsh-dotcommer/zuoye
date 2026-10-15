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
    SOURCE_FEISHU_TASK,
    SOURCE_ISSUE,
    ChatSummaryRecord,
    CommitRecord,
    FeishuTaskRecord,
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

    # v2.4：正文大标题只放团队名，日期移到头部信息行（手机端不再折行断日期）
    assert markdown.startswith("# 测试团队 智能日报\n")
    assert "- 日期：2026-09-18" in markdown
    assert "<h1>测试团队 智能日报</h1>" in report.html
    # 页面标题（浏览器标签/邮件标题栏）仍保留完整标题
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
        recent=[
            ReportStats(date=date(2026, 9, 16)),
            ReportStats(date=date(2026, 9, 17)),
        ],
    )

    # v2.7：工时含提交 10:00 + 任务 11:00 + 评论 12:00，同一工作段 = 2h + 0.5h 收尾
    assert "- 对比上期（2026-09-17）：提交 +1 · 任务 +1 · 沟通 +1 · 工时 +2.5h" in report.markdown
    assert "- 近 3 期：提交 ▁▁█（1 条） · 工时 ▁▁█（2.5h）" in report.markdown
    assert "head-lines" in report.html  # HTML 版与 Markdown 用同一份 view


def test_header_hides_comparison_and_trend_without_history() -> None:
    markdown = _report().markdown

    assert "对比上期" not in markdown
    assert "期：提交" not in markdown  # 只有当期一个点，趋势行不出现


def test_trend_line_requires_three_periods() -> None:
    """v2.4：两期合计容易被误读成当日数据，少于三期整行不出现。"""

    markdown = formatter.generate(
        date(2026, 9, 18),
        MEMBERS,
        COMMITS,
        TASKS,
        MESSAGES,
        STATUSES_OK,
        "测试团队",
        recent=[ReportStats(date=date(2026, 9, 17))],
    ).markdown

    assert "对比上期（2026-09-17）" in markdown
    assert "期：提交" not in markdown


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
    # v2.7：提交 10:00 + 任务变更 11:00 落在同一工作段（该夹具的评论源是失败态，不计入）
    assert "- 工时：1.5h（提交 1 · 任务 1，1 个工作段）" in markdown
    assert "- 工时：团队合计 1.5h · 人均 0.75h（按提交/任务/评论时间推导，非真实考勤）" in markdown


def test_hours_empty_state() -> None:
    markdown = _report().markdown
    zhang_section = markdown.split("## 张三（zhangsan）", 1)[1]

    assert "- 0h（今日无记录）" in zhang_section


def test_hours_still_derived_when_only_commit_source_fails() -> None:
    """v2.7：只要还有活动源成功就用它推导，不再整块作废。"""

    statuses = [
        SourceStatus(name=SOURCE_COMMIT, ok=False, count=0, error="GitHub API 超时"),
        SourceStatus(name=SOURCE_ISSUE, ok=True, count=1),
        SourceStatus(name=SOURCE_DISCUSSION, ok=True, count=1),
    ]
    report = formatter.generate(date(2026, 9, 18), MEMBERS, [], TASKS, MESSAGES, statuses, "测试团队")

    # 红豆：任务 11:00 + 评论 12:00 → 同一工作段
    assert "- 工时：1.5h（任务 1 · 评论 1，1 个工作段）" in report.markdown
    assert "- 工时：团队合计 1.5h · 人均 0.75h" in report.markdown
    assert "工时数据不可用" not in report.markdown
    # 提交板块本身仍然如实标注失败
    assert "数据获取失败（GitHub API 超时）" in report.markdown


def test_hours_unavailable_only_when_all_activity_sources_fail() -> None:
    statuses = [
        SourceStatus(name=SOURCE_COMMIT, ok=False, count=0, error="GitHub API 超时"),
        SourceStatus(name=SOURCE_ISSUE, ok=False, count=0, error="GitHub API 超时"),
        SourceStatus(name=SOURCE_DISCUSSION, ok=False, count=0, error="GitHub API 超时"),
    ]
    report = formatter.generate(date(2026, 9, 18), MEMBERS, [], [], [], statuses, "测试团队")

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
    assert "按提交/任务/评论时间推导，非真实考勤" in html


def test_empty_member_sections_show_placeholder() -> None:
    markdown = _report().markdown
    zhang_section = markdown.split("## 张三（zhangsan）", 1)[1]

    # v2.4：≥2 个空板块合并成一行（协作沟通是失败态，不参与合并）
    assert zhang_section.count("### 代码提交") == 0
    assert "- 今日无记录：代码提交、任务进展" in zhang_section
    assert zhang_section.count("- 今日无记录") == 1
    assert "- 数据获取失败（GitHub API 超时）" in zhang_section


def test_merge_empty_sections_rules() -> None:
    """v2.4 合并规则：≥2 个空板块才合并，工时统计永远不参与合并。"""

    def block(key: str, title: str, state: str, note: str = "今日无记录") -> dict:
        return {"key": key, "title": title, "state": state, "lines": [], "entries": [], "note": note}

    sections = [
        block("commits", "代码提交", "empty"),
        block("tasks", "任务进展", "ok"),
        block("hours", "工时统计", "empty", "0h（今日无记录）"),
    ]
    assert [item["title"] for item in formatter._merge_empty_sections(sections)] == [
        "代码提交",
        "任务进展",
        "工时统计",
    ]

    sections.insert(2, block("messages", "协作沟通", "empty"))
    merged = formatter._merge_empty_sections(sections)

    assert [item["title"] for item in merged] == ["今日无记录", "任务进展", "工时统计"]
    assert merged[0]["note"] == "今日无记录：代码提交、协作沟通"
    assert merged[0]["merged"] is True


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


# ===== v2.4：飞书任务状态快照 =====

FEISHU_TASKS = [
    FeishuTaskRecord(guid="t-done", summary="已经做完的事", status="已完成", due=date(2026, 9, 15)),
    FeishuTaskRecord(guid="t-doing", summary="正在做的事", status="进行中", due=date(2026, 9, 20)),
    FeishuTaskRecord(guid="t-todo", summary="还没开始的事", status="未开始"),
]
TASK_STATUS = SourceStatus(name=SOURCE_FEISHU_TASK, ok=True, count=3)


def _task_report(statuses=None, tasks=None):
    return formatter.generate(
        date(2026, 9, 18),
        MEMBERS,
        COMMITS,
        TASKS,
        MESSAGES,
        statuses if statuses is not None else [*STATUSES_OK, TASK_STATUS],
        "测试团队",
        feishu_tasks=FEISHU_TASKS if tasks is None else tasks,
    )


def test_feishu_task_section_lists_three_states() -> None:
    markdown = _task_report().markdown

    assert "### 任务进展 · 飞书任务" in markdown
    assert "共 3 条：进行中 1 · 未开始 1 · 已完成 1" in markdown
    # 排序：进行中 → 未开始 → 已完成，同组按截止日期升序（无截止排最后）
    doing = markdown.index("- ● 进行中 · 正在做的事（截止 2026-09-20）")
    todo = markdown.index("- ○ 未开始 · 还没开始的事")
    done = markdown.index("- ✓ 已完成 · 已经做完的事（截止 2026-09-15）")
    assert doing < todo < done
    # 小节的物理位置：挂在「任务进展」之后、「工时统计」之前
    assert markdown.index("### 任务进展\n") < doing < markdown.index("### 工时统计")


def test_feishu_task_section_absent_when_source_not_enabled() -> None:
    markdown = formatter.generate(
        date(2026, 9, 18), MEMBERS, COMMITS, TASKS, MESSAGES, STATUSES_OK, "测试团队"
    ).markdown

    assert "飞书任务" not in markdown
    assert "### 任务进展\n" in markdown


def test_feishu_task_section_failed_shows_actionable_note() -> None:
    statuses = [
        *STATUSES_OK,
        SourceStatus(
            name=SOURCE_FEISHU_TASK,
            ok=False,
            count=0,
            error="飞书任务接口未授权：请在开发者后台添加 task:task:read 权限",
        ),
    ]
    markdown = _task_report(statuses=statuses, tasks=[]).markdown

    assert "飞书任务数据获取失败" in markdown
    assert "task:task:read" in markdown


def test_feishu_task_section_empty_state() -> None:
    markdown = _task_report(tasks=[]).markdown

    assert "### 任务进展 · 飞书任务" in markdown
    # v2.5.2：既要覆盖"本来就没任务"，也要覆盖"更早完成的都被隐藏了"
    assert "今日无飞书任务" in markdown


def test_feishu_task_section_marks_backfill_and_truncates() -> None:
    many = [
        FeishuTaskRecord(guid=f"t-{index}", summary=f"任务 {index}", status="进行中")
        for index in range(25)
    ]
    markdown = _task_report(tasks=many).markdown

    # 目标日期不是"今天"时显式标注补跑，避免被读成当天发生的流转
    assert "### 任务进展 · 飞书任务（补跑快照）" in markdown
    assert "共 25 条：进行中 25" in markdown
    assert "- …（其余 5 条见飞书任务）" in markdown
    assert markdown.count("- ● 进行中 · 任务 ") == 20  # 最多列 FEISHU_TASK_LIMIT 条


def test_commit_html_uses_two_row_entries() -> None:
    """v2.4：HTML 侧提交行拆成"主行 + 元信息行"，Markdown 侧保持单行。"""

    report = _report()

    assert '<li class="line-entry">' in report.html
    assert '<span class="line-main">octo/demo feat: 新增静态日报站</span>' in report.html
    assert '<span class="line-meta">' in report.html
    assert "line-meta" in report.html
    # 两行制只在 HTML 生效：Markdown（也就是飞书卡片）仍是原来的单行
    assert (
        "- `octo/demo` [abc1234](https://github.com/octo/demo/commit/abc1234def) "
        "feat: 新增静态日报站（+120/-3，4 个文件：a.py、b.py、c.py、d.py）"
    ) in report.markdown


def test_commit_entries_omit_link_when_url_missing() -> None:
    commits = [replace(COMMITS[0], url="")]

    report = formatter.generate(
        date(2026, 9, 18), MEMBERS, commits, TASKS, MESSAGES, STATUSES, "测试团队"
    )

    assert '<span class="line-meta">abc1234 · ' in report.html
    assert "[abc1234](" not in report.html
