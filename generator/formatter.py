"""日报生成（design.md §4.2，Task 6）。

接口契约：
    generate(date, members, commits, tasks, messages, source_statuses, team_name,
             *, timezone_name="Asia/Shanghai", hours_rules=None) -> DailyReport
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Iterable, Sequence

from generator import hours as hours_module
from generator import template
from shared.config import DEFAULT_ATTRIBUTION_SCOPE, MemberConfig
from shared.models import (
    SOURCE_COMMIT,
    SOURCE_DISCUSSION,
    SOURCE_FEISHU_TASK,
    SOURCE_ISSUE,
    STATUS_DONE,
    STATUS_IN_PROGRESS,
    STATUS_NOT_STARTED,
    TASK_STATUS_ORDER,
    HOURS_EMPTY,
    ChatSummaryRecord,
    CommitRecord,
    DailyReport,
    DataSourceRef,
    FeishuTaskRecord,
    MemberReport,
    MessageRecord,
    ReportStats,
    SourceStatus,
    TaskRecord,
    WORK_HOURS_NOTE,
)

CONTENT_PREVIEW_LIMIT = 140
COMMIT_FILE_LIMIT = 10
SHA_LENGTH = 7
TREND_POINTS = 7
TREND_MIN_POINTS = 3  # v2.4：少于 3 期看不出趋势，且两期合计容易被误读成当日数据
SPARK_BARS = "▁▂▃▄▅▆▇█"
EMPTY_NOTE = "今日无记录"
FAILED_LABEL = "数据获取失败"

# v2.4：数据来源标注
ATTRIBUTION_SEPARATOR = " ｜ "
ATTRIBUTION_TIMEZONE_LABELS = {
    "Asia/Shanghai": "北京时间",
    "Asia/Tokyo": "日本时间",
    "Asia/Singapore": "新加坡时间",
    "UTC": "UTC",
}

# v2.4：飞书任务快照
FEISHU_TASK_LIMIT = 20
FEISHU_TASK_TITLE = "任务进展 · 飞书任务"
FEISHU_TASK_EMPTY_NOTE = "今日无飞书任务"
FEISHU_TASK_FAILED_NOTE = "飞书任务数据获取失败"
FEISHU_TASK_STATUS_MARKS = {
    STATUS_DONE: "✓",
    STATUS_IN_PROGRESS: "●",
    STATUS_NOT_STARTED: "○",
}

# v2.8：团队级管理摘要
ATTENTION_DAYS = 3
ATTENTION_TASK_LIMIT = 5
NEXT_STEP_LIMIT = 3
PROGRESS_LIMIT = 3
ATTENTION_OK_NOTE = "暂无逾期或临近截止事项，所有数据源正常"
NEXT_STEP_EMPTY_NOTE = "暂无其他未完成任务"

# v2.4：内容板块为空时的合并规则（工时统计与飞书任务各自带口径，不参与合并）
MERGEABLE_SECTION_KEYS = ("commits", "tasks", "messages")
MERGE_EMPTY_MIN = 2
MERGED_EMPTY_TITLE = "部分板块无记录"

# 生成层收到的提交已由采集层按采集窗口裁剪，因此推导时不再二次过滤
UNBOUNDED_WINDOW = (
    datetime.min.replace(tzinfo=timezone.utc),
    datetime.max.replace(tzinfo=timezone.utc),
)

SECTION_TITLES = {
    "commits": "代码提交",
    "tasks": "任务进展",
    "hours": "工时统计",
    "messages": "协作沟通",
}


def generate(
    date: date,
    members: Iterable[MemberConfig],
    commits: Sequence[CommitRecord],
    tasks: Sequence[TaskRecord],
    messages: Sequence[MessageRecord],
    source_statuses: Sequence[SourceStatus],
    team_name: str,
    *,
    timezone_name: str = "Asia/Shanghai",
    hours_rules: hours_module.HoursRules | None = None,
    recent: Sequence[ReportStats] = (),
    chat_summaries: Sequence[ChatSummaryRecord] = (),
    feishu_tasks: Sequence[FeishuTaskRecord] = (),
    source_refs: Sequence[DataSourceRef] = (),
    attribution_scope: str = "",
    public_base_url: str = "",
) -> DailyReport:
    """按成员聚合记录，产出 Markdown 与 HTML 双形态日报。

    `recent`（v2.3）为最近几期已保存日报的结构化统计（升序、不含当日），
    用于头部「对比上期」与「近 N 期」两行；`chat_summaries`（v2.3）为飞书群汇总。
    `feishu_tasks`（v2.4）为飞书任务状态快照；`source_refs` 与 `attribution_scope`
    组成对外产物末尾的「数据来源」标注（不传来源时整行不出现）；`public_base_url`
    （v2.8）用于生成当天在线日报入口，为空时入口不出现。
    新增参数都是仅关键字且带默认值，旧调用无需改动。
    """

    member_list = list(members)
    rules = hours_rules or hours_module.HoursRules()
    work_hours = _derive_work_hours(
        member_list, commits, tasks, messages, source_statuses, timezone_name, rules
    ) if rules.enabled else {}

    member_reports = _aggregate(member_list, commits, tasks, messages, work_hours)
    generated_at = datetime.now().astimezone()
    task_section = _feishu_task_section(
        feishu_tasks,
        statuses=source_statuses,
        report_date=date,
        generated_at=generated_at,
    )
    report = DailyReport(
        date=date,
        team_name=team_name,
        members=member_reports,
        generated_at=generated_at,
        source_statuses=list(source_statuses),
        total_hours=round(sum(item.hours for item in work_hours.values()), 2),
        member_count=len(member_reports),
        commit_count=len(commits),
        task_count=len(tasks),
        message_count=len(messages),
        chat_message_count=sum(item.message_count for item in chat_summaries),
        recent_stats=list(recent),
        chat_summaries=list(chat_summaries),
        feishu_tasks=list(feishu_tasks),
        public_url=_public_report_url(public_base_url, date),
    )
    report.attribution = build_attribution(
        generated_at=generated_at,
        source_refs=source_refs,
        scope=attribution_scope,
        timezone_name=timezone_name,
    )
    view = build_view(report, feishu_task_section=task_section)
    report.markdown = render_markdown(view)
    report.html = template.render_report_html(view)
    report.email_html = template.render_email_html(view)
    return report


def build_view(report: DailyReport, *, feishu_task_section: dict | None = None) -> dict:
    """把日报转成模板友好的视图模型（Markdown 与 HTML 共用同一份数据）。"""

    statuses = {status.name: status for status in report.source_statuses}
    hours_enabled = any(member.work_hours is not None for member in report.members)
    single_member = len(report.members) == 1
    if feishu_task_section is None:
        # 直接调用 build_view(report) 的场景（站点层二次渲染、测试）：按已有数据重建
        feishu_task_section = _feishu_task_section(
            report.feishu_tasks,
            statuses=report.source_statuses,
            report_date=report.date,
            generated_at=report.generated_at,
        )
    return {
        "title": f"{report.team_name} 智能日报 · {report.date.isoformat()}",
        # v2.4：正文大标题不再带日期，日期移到头部信息行，避免手机端折行断日期
        "heading": f"{report.team_name} 智能日报",
        "date": report.date.isoformat(),
        "date_label": report.date.isoformat(),
        "team_name": report.team_name,
        "team_label": _team_label(report, single_member),
        "single_member": single_member,
        "generated_at": _format_moment(report.generated_at),
        "hours_summary": _hours_summary(report) if hours_enabled else None,
        "extra_lines": _extra_lines(report),
        "management": _management_summary(report),
        "attribution": report.attribution,
        "source_summary": [
            {
                "label": status.label,
                "count": status.count,
                "ok": status.ok,
                "error": status.error,
            }
            for status in report.source_statuses
        ],
        "members": [
            {
                "name": member.name,
                "github_username": member.github_username,
                "sections": _member_sections(
                    member,
                    statuses,
                    feishu_task_section=feishu_task_section if index == 0 else None,
                ),
            }
            for index, member in enumerate(report.members)
        ],
    }


def _member_sections(
    member: MemberReport,
    statuses: dict,
    *,
    feishu_task_section: dict | None = None,
) -> list[dict]:
    """成员段落固定顺序：代码提交 → 任务进展（含飞书任务子小节）→ 工时统计 → 协作沟通。"""

    sections = [
        _section(
            "commits",
            _commit_items(member.commits),
            statuses.get(SOURCE_COMMIT),
            entries=_commit_entries(member.commits),
        ),
        _section("tasks", _task_items(member.tasks, member), statuses.get(SOURCE_ISSUE)),
    ]
    if feishu_task_section is not None:
        sections.append(feishu_task_section)
    hours_section = _hours_section(member)
    if hours_section is not None:
        sections.append(hours_section)
    sections.append(
        _section(
            "messages",
            _message_items(member.messages),
            statuses.get(SOURCE_DISCUSSION),
        )
    )
    return _merge_empty_sections(sections)


def _merge_empty_sections(sections: list[dict]) -> list[dict]:
    """v2.4：同一次日报里空板块 ≥ 2 个时合并成一行，避免半屏都是"今日无记录"。

    只合并内容板块（代码提交 / 任务进展 / 协作沟通）；工时统计与飞书任务
    各自带口径说明，仍按原样呈现。合并后的板块留在第一个空板块的位置，
    其余空板块移除，有内容的板块顺序不变。
    """

    empty_titles = [
        section["title"]
        for section in sections
        if section["state"] == "empty" and section["key"] in MERGEABLE_SECTION_KEYS
    ]
    if len(empty_titles) < MERGE_EMPTY_MIN:
        return sections

    merged = {
        "key": "empty_summary",
        "title": MERGED_EMPTY_TITLE,
        "state": "empty",
        "lines": [],
        "entries": [],
        "note": "、".join(empty_titles),
        "merged": True,
    }
    out: list[dict] = []
    inserted = False
    for section in sections:
        if section["state"] == "empty" and section["key"] in MERGEABLE_SECTION_KEYS:
            if not inserted:
                out.append(merged)
                inserted = True
            continue
        out.append(section)
    return out


def _team_label(report: DailyReport, single_member: bool) -> str:
    """头部「- 团队：」的取值（v2.2）：单人团队时并入成员身份，避免与成员标题重复。"""

    if not single_member:
        return report.team_name
    username = (report.members[0].github_username or "").strip()
    if not username:
        return report.team_name
    return f"{report.team_name}（@{username}）"


def _extra_lines(report: DailyReport) -> list[str]:
    """头部补充行（v2.3）：飞书群汇总 → 对比上期 → 近 N 期趋势，空行不出现。"""

    lines: list[str] = []
    chat = _chat_line(report.chat_summaries)
    if chat:
        lines.append(chat)
    comparison = _comparison_line(report.recent_stats, report)
    if comparison:
        lines.append(comparison)
    trend = _trend_line(report.recent_stats, report)
    if trend:
        lines.append(trend)
    return lines


def _public_report_url(base_url: str, report_date: date) -> str:
    """把配置的站点根地址拼成当天详情页；未配置时返回空串。"""

    root = (base_url or "").strip().rstrip("/")
    if not root:
        return ""
    return f"{root}/daily-report-{report_date.isoformat()}.html"


def _management_summary(report: DailyReport) -> dict:
    """v2.8：团队级管理摘要，供三端共用。

    只消费日报已有快照，不新增 API 请求。需要关注的范围按目标日计算，
    因此补跑历史日期时也会以那一天为基准。
    """

    statuses = {status.name: status for status in report.source_statuses}
    overview: list[str] = []

    if SOURCE_FEISHU_TASK in statuses:
        counts = {name: 0 for name in TASK_STATUS_ORDER}
        for task in report.feishu_tasks:
            counts[task.status] = counts.get(task.status, 0) + 1
        overdue = sum(
            1
            for task in report.feishu_tasks
            if task.status != STATUS_DONE and task.due is not None and task.due < report.date
        )
        overview.append(
            f"飞书任务：已完成 {counts[STATUS_DONE]} · 进行中 {counts[STATUS_IN_PROGRESS]}"
            f" · 未开始 {counts[STATUS_NOT_STARTED]} · 逾期 {overdue}"
        )

    overview.append(_github_activity_line(report))
    progress = _progress_lines(report)

    attention_tasks = _attention_tasks(report)
    attention = [
        f"{_linked_feishu_task(task)}（{task.status} · {_due_status(task, report.date)}）"
        for task in attention_tasks
    ]
    attention.extend(
        f"数据源异常：{status.label}（{status.error or '未知原因'}）"
        for status in report.source_statuses
        if not status.ok
    )
    if not attention:
        attention = [ATTENTION_OK_NOTE]

    attention_keys = {_task_key(task) for task in attention_tasks}
    next_steps = [
        f"{task.status} · "
        f"{_linked_feishu_task(task)}{_feishu_task_due(task)}"
        for task in _next_tasks(report, attention_keys)
    ]
    if not next_steps:
        next_steps = [NEXT_STEP_EMPTY_NOTE]

    return {
        "online_url": report.public_url,
        "overview": overview,
        "progress": progress,
        "attention": attention,
        "next_steps": next_steps,
    }


def _github_activity_line(report: DailyReport) -> str:
    """团队当日 GitHub 活动的紧凑汇总。"""

    commits = [record for member in report.members for record in member.commits]
    tasks = [record for member in report.members for record in member.tasks]
    messages = [record for member in report.members for record in member.messages]
    additions = sum(record.additions for record in commits)
    deletions = sum(record.deletions for record in commits)

    files: set[str] = set()
    unnamed_file_changes = 0
    for record in commits:
        if record.files:
            files.update(record.files)
        else:
            unnamed_file_changes += record.files_changed
    file_count = len(files) + unnamed_file_changes

    done = sum(1 for record in tasks if record.status_to == STATUS_DONE)
    advanced = sum(1 for record in tasks if record.status_to != STATUS_DONE)
    return (
        f"GitHub 活动：提交 {len(commits)} 个（+{additions}/-{deletions}，涉及文件 {file_count} 个）"
        f" · Issue 完成 {done} · 推进 {advanced} · 互动 {len(messages)} 条"
    )


def _progress_lines(report: DailyReport) -> list[str]:
    """重点进展：飞书已完成 → Issue 已完成 → 最新提交，最多三条。"""

    items: list[str] = []
    completed_feishu = sorted(
        (task for task in report.feishu_tasks if task.status == STATUS_DONE),
        key=lambda task: task.completed_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    for task in completed_feishu:
        if len(items) >= PROGRESS_LIMIT:
            break
        items.append(f"完成飞书任务 {_linked_feishu_task(task)}")

    completed_issues = sorted(
        (
            task
            for member in report.members
            for task in member.tasks
            if task.status_to == STATUS_DONE
        ),
        key=lambda task: task.updated_at,
        reverse=True,
    )
    for task in completed_issues:
        if len(items) >= PROGRESS_LIMIT:
            break
        items.append(f"完成 GitHub Issue {_task_reference(task)}")

    commits = sorted(
        (record for member in report.members for record in member.commits),
        key=lambda record: record.timestamp,
        reverse=True,
    )
    for record in commits:
        if len(items) >= PROGRESS_LIMIT:
            break
        short = (record.sha or "").strip()[:SHA_LENGTH]
        reference = f"[{short}]({record.url}) " if short and record.url else (f"{short} " if short else "")
        items.append(f"提交 {reference}{record.message or '(无提交信息)'}")
    return items


def _attention_tasks(report: DailyReport) -> list[FeishuTaskRecord]:
    """未完成且已逾期、今天到期或未来三天内到期的任务。"""

    horizon = report.date.fromordinal(report.date.toordinal() + ATTENTION_DAYS)
    return sorted(
        (
            task
            for task in report.feishu_tasks
            if task.status != STATUS_DONE and task.due is not None and task.due <= horizon
        ),
        key=lambda task: (task.due or date.max, _feishu_task_sort_key(task)),
    )[:ATTENTION_TASK_LIMIT]


def _next_tasks(
    report: DailyReport,
    excluded_keys: set[str],
) -> list[FeishuTaskRecord]:
    """下一步：进行中优先，其次未开始；排除已在“需要关注”中出现的任务。"""

    active = [
        task
        for task in report.feishu_tasks
        if task.status in (STATUS_IN_PROGRESS, STATUS_NOT_STARTED)
        and _task_key(task) not in excluded_keys
    ]
    return sorted(active, key=_feishu_task_sort_key)[:NEXT_STEP_LIMIT]


def _task_key(task: FeishuTaskRecord) -> str:
    if task.guid:
        return task.guid
    return f"{task.summary}|{task.due.isoformat() if task.due else ''}"


def _linked_feishu_task(task: FeishuTaskRecord) -> str:
    title = task.summary or "(无标题)"
    return f"[{title}]({task.url})" if task.url else title


def _task_reference(task: TaskRecord) -> str:
    prefix = ""
    if task.number:
        prefix = f"[#{task.number}]({task.url}) " if task.url else f"#{task.number} "
    return f"{prefix}{task.title or '(无标题)'}"


def _due_status(task: FeishuTaskRecord, report_date: date) -> str:
    if task.due is None:
        return "未设置截止日期"
    if task.due < report_date:
        return f"逾期 {(report_date - task.due).days} 天"
    if task.due == report_date:
        return "今天到期"
    return f"{task.due.isoformat()} 到期"


def _chat_line(summaries: Sequence[ChatSummaryRecord]) -> str:
    if not summaries:
        return ""
    parts = [
        f"{item.chat_name} {item.message_count} 条 · {item.speaker_count} 人发言"
        for item in summaries
    ]
    return "飞书群：" + "；".join(parts)


def _comparison_line(recent: Sequence[ReportStats], report: DailyReport) -> str:
    """与"上一期已保存的日报"对比（v2.3）；无历史时整行不出现。"""

    baseline = recent[-1] if recent else None
    if baseline is None or baseline.date >= report.date:
        return ""
    parts = [
        f"提交 {_delta_text(report.commit_count - baseline.commit_count)}",
        f"任务 {_delta_text(report.task_count - baseline.task_count)}",
        f"沟通 {_delta_text(report.message_count - baseline.message_count)}",
        f"工时 {_delta_text(report.total_hours - baseline.total_hours, unit='h')}",
    ]
    return f"对比上期（{baseline.date.isoformat()}）：" + " · ".join(parts)


def _trend_line(recent: Sequence[ReportStats], report: DailyReport) -> str:
    """近 N 期（含当日）的迷你趋势；不足两期不显示（单点看不出趋势）。"""

    series = [item for item in recent if item.date < report.date]
    series.append(_stats_of(report))
    series = series[-TREND_POINTS:]
    if len(series) < TREND_MIN_POINTS:
        return ""
    commits = [item.commit_count for item in series]
    hours = [item.total_hours for item in series]
    return (
        f"近 {len(series)} 期：提交 {_sparkline(commits)}（{sum(commits)} 条）"
        f" · 工时 {_sparkline(hours)}（{_format_hours(sum(hours))}h）"
    )


def _stats_of(report: DailyReport) -> ReportStats:
    return ReportStats(
        date=report.date,
        commit_count=report.commit_count,
        task_count=report.task_count,
        message_count=report.message_count,
        chat_message_count=report.chat_message_count,
        total_hours=report.total_hours,
    )


def _sparkline(values: Sequence[float]) -> str:
    """把一串数值归一化成 8 档块字符；全 0 时统一最低档，不虚高。"""

    if not values:
        return ""
    peak = max(values)
    top = len(SPARK_BARS) - 1
    if peak <= 0:
        return SPARK_BARS[0] * len(values)
    return "".join(SPARK_BARS[min(top, round(value / peak * top))] for value in values)


def _delta_text(value: float, *, unit: str = "") -> str:
    if abs(value) < 1e-9:
        return f"±0{unit}"
    sign = "+" if value > 0 else "-"
    return f"{sign}{_format_hours(abs(value))}{unit}"


def render_markdown(view: dict) -> str:
    """渲染 Markdown 版本日报。"""

    lines = [
        f"# {view['heading']}",
        "",
        f"- 日期：{view['date_label']}",
        f"- 团队：{view.get('team_label') or view['team_name']}",
        f"- 生成时间：{view['generated_at']}",
        "- 数据源：" + " · ".join(_source_summary_line(item) for item in view["source_summary"]),
    ]
    if view.get("hours_summary"):
        summary = view["hours_summary"]
        lines.append(
            f"- 工时：团队合计 {summary['total']}h · 人均 {summary['average']}h（{WORK_HOURS_NOTE}）"
        )
    lines.extend(f"- {line}" for line in view.get("extra_lines") or [])
    management = view.get("management") or {}
    if management.get("online_url"):
        lines.append(f"- 在线日报：[查看当天完整日报]({management['online_url']})")
    lines.append("")

    if management:
        lines.extend(["## 管理摘要", "", "### 今日概览"])
        lines.extend(f"- {item}" for item in management.get("overview") or [])
        if management.get("progress"):
            lines.append("- 重点进展：" + "；".join(management["progress"]))
        lines.extend(["", "### 需要关注"])
        lines.extend(f"- {item}" for item in management.get("attention") or [])
        lines.extend(["", "### 下一步"])
        lines.extend(f"- {item}" for item in management.get("next_steps") or [])
        lines.append("")

    if not view["members"]:
        lines.append("（没有可输出的成员段落）")
        return _finish_markdown(lines, view)

    for member in view["members"]:
        if not view.get("single_member"):
            # 单人团队：身份已写进头部"- 团队：姓名（@username）"，不再重复成员标题
            lines.append(f"## {member['name']}（{member['github_username']}）")
            lines.append("")
        for section in member["sections"]:
            lines.append(f"### {section['title']}")
            if section["state"] == "ok":
                lines.extend(section["lines"])
            else:
                lines.append(f"- {section['note']}")
            lines.append("")
    return _finish_markdown(lines, view)


def _finish_markdown(lines: list[str], view: dict) -> str:
    """收尾：追加「数据来源」标注（v2.4）；未启用时产物与旧版逐字节一致。"""

    attribution = (view.get("attribution") or "").strip()
    if attribution:
        lines.extend(["", attribution])
    return "\n".join(lines).rstrip() + "\n"


def find_unmapped(
    members: Iterable[MemberConfig],
    commits: Sequence[CommitRecord],
    tasks: Sequence[TaskRecord],
    messages: Sequence[MessageRecord],
) -> set[str]:
    """返回未能匹配到成员映射表的身份集合（供编排层记日志，默认忽略这些记录）。"""

    member_list = list(members)
    identities = {record.author for record in commits}
    identities |= {record.assignee for record in tasks if record.assignee}
    identities |= {record.sender for record in messages}
    return {
        identity
        for identity in identities
        if identity and not any(member.matches(identity) for member in member_list)
    }


def _aggregate(
    members: Iterable[MemberConfig],
    commits: Sequence[CommitRecord],
    tasks: Sequence[TaskRecord],
    messages: Sequence[MessageRecord],
    work_hours: dict | None = None,
) -> list[MemberReport]:
    member_list = list(members)
    hours_map = work_hours or {}
    reports: list[MemberReport] = [
        MemberReport(
            name=member.name,
            github_username=member.github_username,
            work_hours=hours_map.get(member.github_username.strip().lower()),
        )
        for member in member_list
    ]

    def locate(identity: str) -> MemberReport | None:
        for member, report in zip(member_list, reports):
            if member.matches(identity):
                return report
        return None

    for commit in commits:
        report = locate(commit.author)
        if report is not None:
            report.commits.append(commit)
    for task in tasks:
        report = locate(task.assignee)
        if report is not None:
            report.tasks.append(task)
    for message in messages:
        report = locate(message.sender)
        if report is not None:
            report.messages.append(message)

    for report in reports:
        report.commits.sort(key=lambda item: item.timestamp)
        report.tasks.sort(key=lambda item: item.updated_at)
        report.messages.sort(key=lambda item: item.timestamp)
    return reports


def _section(
    key: str,
    items: list[str],
    status: SourceStatus | None,
    *,
    entries: list[dict] | None = None,
) -> dict:
    """构造一个板块视图；`lines` 给 Markdown/飞书，`entries` 给 HTML 的两行布局。"""

    title = SECTION_TITLES[key]
    base = {"key": key, "title": title, "entries": entries or []}
    if status is not None and not status.ok:
        reason = status.error or "未知原因"
        return {**base, "state": "failed", "lines": [], "note": f"{FAILED_LABEL}（{reason}）"}
    if not items:
        return {**base, "state": "empty", "lines": [], "note": EMPTY_NOTE}
    return {**base, "state": "ok", "lines": items, "note": ""}


def _feishu_task_section(
    tasks: Sequence[FeishuTaskRecord],
    *,
    statuses: Sequence[SourceStatus],
    report_date: date,
    generated_at: datetime,
) -> dict | None:
    """飞书任务状态快照小节（v2.4），附在「任务进展」板块之后。

    返回 None 表示本次运行根本没有这个数据源（未启用），此时连小节标题都不出现，
    行为与 v2.3 完全一致。飞书任务没有"时间窗"概念，所以标题里显式标注快照时间，
    补跑历史日期时再额外标注「补跑快照」，避免被误读成当天发生的流转。
    """

    status = next((item for item in statuses if item.name == SOURCE_FEISHU_TASK), None)
    if status is None:
        return None

    title = FEISHU_TASK_TITLE
    if report_date != generated_at.date():
        title += "（补跑快照）"
    base = {"key": SOURCE_FEISHU_TASK, "title": title, "sub": True, "entries": []}

    if not status.ok:
        reason = status.error or "未知原因"
        return {**base, "state": "failed", "lines": [], "note": f"{FEISHU_TASK_FAILED_NOTE}（{reason}）"}
    if not tasks:
        return {**base, "state": "empty", "lines": [], "note": FEISHU_TASK_EMPTY_NOTE}

    counts: dict[str, int] = {name: 0 for name in TASK_STATUS_ORDER}
    for task in tasks:
        counts[task.status] = counts.get(task.status, 0) + 1
    breakdown = " · ".join(
        f"{name} {counts[name]}" for name in TASK_STATUS_ORDER if counts.get(name)
    )
    lines = [f"- 截至 {_format_moment(generated_at)} · 共 {len(tasks)} 条：{breakdown}"]
    ordered = sorted(tasks, key=_feishu_task_sort_key)[:FEISHU_TASK_LIMIT]
    lines.extend(
        f"- {FEISHU_TASK_STATUS_MARKS.get(task.status, '·')} {task.status} · "
        f"{task.summary}{_feishu_task_due(task)}"
        for task in ordered
    )
    if len(tasks) > FEISHU_TASK_LIMIT:
        lines.append(f"- …（其余 {len(tasks) - FEISHU_TASK_LIMIT} 条见飞书任务）")
    return {**base, "state": "ok", "lines": lines, "note": ""}


def _feishu_task_sort_key(task: FeishuTaskRecord) -> tuple:
    """进行中 → 未开始 → 已完成；同组内按截止日期升序（无截止的排最后）。"""

    try:
        rank = TASK_STATUS_ORDER.index(task.status)
    except ValueError:
        rank = len(TASK_STATUS_ORDER)
    return (rank, task.due or date.max, task.summary)


def _feishu_task_due(task: FeishuTaskRecord) -> str:
    return f"（截止 {task.due.isoformat()}）" if task.due else ""


def _hours_section(member: MemberReport) -> dict | None:
    """工时板块（v1.1）：仅当配置启用工时时出现。"""

    record = member.work_hours
    if record is None:
        return None
    title = SECTION_TITLES["hours"]
    if not record.available:
        return {
            "key": "hours",
            "title": title,
            "state": "failed",
            "lines": [],
            "entries": [],
            "note": f"工时数据不可用（{record.detail or '未知原因'}）",
        }
    if record.state == HOURS_EMPTY:
        return {
            "key": "hours",
            "title": title,
            "state": "empty",
            "lines": [],
            "entries": [],
            "note": f"0h（{EMPTY_NOTE}）",
        }
    return {
        "key": "hours",
        "title": title,
        "state": "ok",
        "lines": [f"- 工时：{_format_hours(record.hours)}h（{record.detail}）"],
        "entries": [],
        "note": "",
    }


def _hours_summary(report: DailyReport) -> dict:
    member_count = report.member_count or len(report.members)
    average = report.total_hours / member_count if member_count else 0.0
    return {
        "total": _format_hours(report.total_hours),
        "average": _format_hours(average),
        "member_count": member_count,
        "note": WORK_HOURS_NOTE,
    }


def _derive_work_hours(
    members: Sequence[MemberConfig],
    commits: Sequence[CommitRecord],
    tasks: Sequence[TaskRecord],
    messages: Sequence[MessageRecord],
    statuses: Sequence[SourceStatus],
    timezone_name: str,
    rules: hours_module.HoursRules,
) -> dict:
    """按会话法推导工时（v2.7）。

    活动有三个来源：提交、Issue 状态变更、评论。**三个源全部失败**才判"不可用"；
    只要有一个成功就用成功的那些推导——失败的数据源已经在头部徽章里标出来了，
    这里不再把整块工时一起作废（旧规则是"提交源失败就全员不可用"，v2.7 放宽）。
    """

    activity_sources = (SOURCE_COMMIT, SOURCE_ISSUE, SOURCE_DISCUSSION)
    relevant = [status for status in statuses if status.name in activity_sources]
    if relevant and not any(status.ok for status in relevant):
        reason = next((status.error for status in relevant if status.error), "")
        return hours_module.unavailable_records(members, reason or "所有活动数据源均不可用")

    def source_ok(name: str) -> bool:
        """没记录状态的数据源按"可用"处理（直接调用生成层的场景）。"""

        status = next((item for item in statuses if item.name == name), None)
        return status is None or status.ok

    # 传进来的活动已由采集层按采集窗口裁剪，这里不再二次过滤
    return hours_module.derive(
        members,
        commits if source_ok(SOURCE_COMMIT) else [],
        UNBOUNDED_WINDOW,
        timezone_name,
        rules,
        tasks=tasks if source_ok(SOURCE_ISSUE) else [],
        messages=messages if source_ok(SOURCE_DISCUSSION) else [],
    )


def _format_hours(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def _commit_items(commits: Sequence[CommitRecord]) -> list[str]:
    return [
        f"- `{record.repo}` {_commit_link(record)}{record.message or '(无提交信息)'}{_commit_stats(record)}"
        for record in commits
    ]


def _commit_entries(commits: Sequence[CommitRecord]) -> list[dict]:
    """提交行的 HTML 两行布局（v2.4）。

    主行放"仓库 + 提交信息"，元信息行放短号链接 + 变更统计；这样手机端不会
    把一条提交折成三行。Markdown/飞书仍用单行（`lines`），形态不变。
    """

    entries: list[dict] = []
    for record in commits:
        short = (record.sha or "").strip()[:SHA_LENGTH]
        meta: list[str] = []
        if short:
            meta.append(f"[{short}]({record.url})" if record.url else short)
        meta.append(_commit_stats_text(record))
        entries.append(
            {
                "main": f"{record.repo} {record.message or '(无提交信息)'}".strip(),
                "meta": " · ".join(meta),
            }
        )
    return entries


def _commit_link(record: CommitRecord) -> str:
    """提交短号 + 链接；SHA 缺失时整段省略，不留空壳。"""

    short = (record.sha or "").strip()[:SHA_LENGTH]
    if not short:
        return ""
    if record.url:
        return f"[{short}]({record.url}) "
    return f"{short} "


def _commit_stats(record: CommitRecord) -> str:
    """提交行的变更统计；有文件名时在数量后列出（最多 COMMIT_FILE_LIMIT 个，超出以 `…` 结尾）。

    文件名缺失（未取详情统计、详情请求失败）时退回只报数量的旧格式，不出现空冒号。
    """

    return f"（{_commit_stats_text(record)}）"


def _commit_stats_text(record: CommitRecord) -> str:
    summary = f"+{record.additions}/-{record.deletions}，{record.files_changed} 个文件"
    if record.files:
        shown = "、".join(record.files[:COMMIT_FILE_LIMIT])
        if len(record.files) > COMMIT_FILE_LIMIT:
            shown += "、…"
        summary += f"：{shown}"
    return summary


def _task_items(tasks: Sequence[TaskRecord], member: MemberReport) -> list[str]:
    return [
        f"- {_task_headline(record)}{_task_context(record, member)}" for record in tasks
    ]


def _task_headline(record: TaskRecord) -> str:
    """任务行的标题段：优先 `[#编号](链接)`，缺链接时退回纯编号/纯标题。"""

    prefix = ""
    if record.number:
        prefix = f"[#{record.number}]({record.url}) " if record.url else f"#{record.number} "
    return f"{prefix}{record.title or '(无标题)'}：{record.status_from} → {record.status_to}"


def _task_context(record: TaskRecord, member: MemberReport) -> str:
    """任务行的括号补充：标签 / 指派 / 评论数；空片段整体不出现。

    指派人与本段成员一致时不显示——日报按人聚合，写自己名字是噪音。
    """

    parts: list[str] = []
    if record.labels:
        parts.append("标签：" + "、".join(record.labels))
    assignee = (record.assignee or "").strip()
    if assignee and assignee.lower() != (member.github_username or "").strip().lower():
        parts.append(f"指派：{assignee}")
    if record.comment_count > 0:
        parts.append(f"{record.comment_count} 条评论")
    return f"（{' · '.join(parts)}）" if parts else ""


def _message_items(messages: Sequence[MessageRecord]) -> list[str]:
    return [
        f"- {_message_source(record)} {record.sender}：{_preview(record.content)}"
        for record in messages
    ]


def _message_source(record: MessageRecord) -> str:
    """讨论来源：有链接时输出 Markdown 链接（HTML 侧由 inline_links 过滤器转成 <a>）。"""

    label = record.source or "(未知来源)"
    return f"[{label}]({record.url})" if record.url else f"[{label}]"


def _preview(content: str) -> str:
    text = " ".join((content or "").split())
    if len(text) <= CONTENT_PREVIEW_LIMIT:
        return text
    return text[:CONTENT_PREVIEW_LIMIT] + "…"


def _format_moment(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M")


def build_attribution(
    *,
    generated_at: datetime,
    source_refs: Sequence[DataSourceRef],
    scope: str,
    timezone_name: str = "",
) -> str:
    """组装对外产物末尾的「数据来源」标注（v2.4）。

    三要素固定顺序：数据源全称 → 采集时间 → 授权使用范围。没有任何数据源时
    返回空串，调用方据此决定不渲染——这样旧调用与旧测试的产物保持字节不变。
    """

    refs = [ref for ref in source_refs if ref.label or ref.full_name]
    if not refs:
        return ""
    zone = ATTRIBUTION_TIMEZONE_LABELS.get(timezone_name, timezone_name or "本地时间")
    return ATTRIBUTION_SEPARATOR.join(
        (
            "数据来源：" + "、".join(ref.render() for ref in refs),
            f"采集时间：{_format_moment(generated_at)}（{zone}）",
            f"授权范围：{scope.strip() or DEFAULT_ATTRIBUTION_SCOPE}",
        )
    )


def _source_summary_line(item: dict) -> str:
    if item["ok"]:
        return f"{item['label']} {item['count']} 条"
    return f"{item['label']} 数据获取失败"
