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
from shared.config import MemberConfig
from shared.models import (
    SOURCE_COMMIT,
    SOURCE_DISCUSSION,
    SOURCE_ISSUE,
    HOURS_EMPTY,
    ChatSummaryRecord,
    CommitRecord,
    DailyReport,
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
TREND_MIN_POINTS = 2
SPARK_BARS = "▁▂▃▄▅▆▇█"
EMPTY_NOTE = "今日无记录"
FAILED_LABEL = "数据获取失败"

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
) -> DailyReport:
    """按成员聚合记录，产出 Markdown 与 HTML 双形态日报。

    `recent`（v2.3）为最近几期已保存日报的结构化统计（升序、不含当日），
    用于头部「对比上期」与「近 N 期」两行；`chat_summaries`（v2.3）为飞书群汇总。
    两者都是仅关键字参数且带默认值，旧调用无需改动。
    """

    member_list = list(members)
    rules = hours_rules or hours_module.HoursRules()
    work_hours = _derive_work_hours(
        member_list, commits, source_statuses, timezone_name, rules
    ) if rules.enabled else {}

    member_reports = _aggregate(member_list, commits, tasks, messages, work_hours)
    generated_at = datetime.now().astimezone()
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
    )
    view = build_view(report)
    report.markdown = render_markdown(view)
    report.html = template.render_report_html(view)
    return report


def build_view(report: DailyReport) -> dict:
    """把日报转成模板友好的视图模型（Markdown 与 HTML 共用同一份数据）。"""

    statuses = {status.name: status for status in report.source_statuses}
    hours_enabled = any(member.work_hours is not None for member in report.members)
    single_member = len(report.members) == 1
    return {
        "title": f"{report.team_name} 智能日报 · {report.date.isoformat()}",
        "date": report.date.isoformat(),
        "team_name": report.team_name,
        "team_label": _team_label(report, single_member),
        "single_member": single_member,
        "generated_at": _format_moment(report.generated_at),
        "hours_summary": _hours_summary(report) if hours_enabled else None,
        "extra_lines": _extra_lines(report),
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
                "sections": _member_sections(member, statuses),
            }
            for member in report.members
        ],
    }


def _member_sections(member: MemberReport, statuses: dict) -> list[dict]:
    """成员段落固定顺序：代码提交 → 任务进展 → 工时统计 → 协作沟通。"""

    sections = [
        _section("commits", _commit_items(member.commits), statuses.get(SOURCE_COMMIT)),
        _section("tasks", _task_items(member.tasks, member), statuses.get(SOURCE_ISSUE)),
    ]
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
    return sections


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
        f"# {view['title']}",
        "",
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
    lines.append("")
    if not view["members"]:
        lines.append("（没有可输出的成员段落）")
        return "\n".join(lines).rstrip() + "\n"

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


def _section(key: str, items: list[str], status: SourceStatus | None) -> dict:
    title = SECTION_TITLES[key]
    if status is not None and not status.ok:
        reason = status.error or "未知原因"
        return {"title": title, "state": "failed", "lines": [], "note": f"{FAILED_LABEL}（{reason}）"}
    if not items:
        return {"title": title, "state": "empty", "lines": [], "note": EMPTY_NOTE}
    return {"title": title, "state": "ok", "lines": items, "note": ""}


def _hours_section(member: MemberReport) -> dict | None:
    """工时板块（v1.1）：仅当配置启用工时时出现。"""

    record = member.work_hours
    if record is None:
        return None
    title = SECTION_TITLES["hours"]
    if not record.available:
        return {
            "title": title,
            "state": "failed",
            "lines": [],
            "note": f"工时数据不可用（{record.detail or '未知原因'}）",
        }
    if record.state == HOURS_EMPTY:
        return {"title": title, "state": "empty", "lines": [], "note": f"0h（{EMPTY_NOTE}）"}
    return {
        "title": title,
        "state": "ok",
        "lines": [f"- 工时：{_format_hours(record.hours)}h（{record.commit_count} 条提交，{record.session_count} 个工作段）"],
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
    statuses: Sequence[SourceStatus],
    timezone_name: str,
    rules: hours_module.HoursRules,
) -> dict:
    """提交数据源失败时全员标记不可用，否则按会话法推导。"""

    commit_status = next((status for status in statuses if status.name == SOURCE_COMMIT), None)
    if commit_status is not None and not commit_status.ok:
        return hours_module.unavailable_records(members, commit_status.error)
    # 传进来的提交已由采集层按采集窗口裁剪，这里不再二次过滤
    return hours_module.derive(members, commits, UNBOUNDED_WINDOW, timezone_name, rules)


def _format_hours(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def _commit_items(commits: Sequence[CommitRecord]) -> list[str]:
    return [
        f"- `{record.repo}` {_commit_link(record)}{record.message or '(无提交信息)'}{_commit_stats(record)}"
        for record in commits
    ]


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

    summary = f"（+{record.additions}/-{record.deletions}，{record.files_changed} 个文件"
    if record.files:
        shown = "、".join(record.files[:COMMIT_FILE_LIMIT])
        if len(record.files) > COMMIT_FILE_LIMIT:
            shown += "、…"
        summary += f"：{shown}"
    return summary + "）"


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


def _source_summary_line(item: dict) -> str:
    if item["ok"]:
        return f"{item['label']} {item['count']} 条"
    return f"{item['label']} 数据获取失败"
