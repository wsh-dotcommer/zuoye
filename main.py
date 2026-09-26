"""智能日报生成器 — 主编排入口（design.md §2，Task 9）。

用法：
    python main.py --check                        # 体检：配置、环境变量、GitHub / SMTP / 飞书连通性
    python main.py --dry-run                      # 采集 + 生成 + 站点渲染，不推送
    python main.py                                # 完整流程（默认采集当日 00:00 → 现在）
    python main.py --date 2026-09-18               # 补跑历史某日
    python main.py --since 2026-09-17 --until 2026-09-19
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from collector import github_commit, github_discussion, github_issue
from generator import formatter
from generator.hours import HoursRules
from generator.site import SiteConfig, detail_file_name, render_site
from notifier import email as email_notifier
from notifier import lark_bot
from shared.config import Config, MemberConfig, load_config
from shared.errors import CollectorError, ConfigError
from shared.logger import JsonLineLogger, build_logger
from shared.models import (
    SOURCE_COMMIT,
    SOURCE_DISCUSSION,
    SOURCE_ISSUE,
    SourceStatus,
)
from shared.storage import Storage

EXIT_OK = 0
EXIT_CHECK_FAILED = 1
EXIT_ALL_SOURCES_FAILED = 2
HISTORY_LIMIT = 90


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"[配置错误] {exc}", file=sys.stderr)
        return EXIT_CHECK_FAILED

    logger = build_logger(config.report.log_path)
    logger.info(
        "run_started",
        config=str(config.path),
        repos=[repo.full_name for repo in config.repos],
        members=len(config.members),
    )

    if args.check:
        return _run_checks(config, logger)
    return _run_pipeline(config, args, logger)


def _run_pipeline(config: Config, args: argparse.Namespace, logger: JsonLineLogger) -> int:
    timezone = ZoneInfo(config.team.timezone)
    try:
        start, end, target_date = _resolve_window(args, timezone)
    except (ConfigError, ValueError) as exc:
        logger.error("window_invalid", error=str(exc))
        return EXIT_CHECK_FAILED

    explicit_window = bool(args.date or args.since or args.until)
    if not explicit_window and not _is_working_day(target_date, config):
        logger.info("skipped_non_working_day", date=target_date.isoformat())
        return EXIT_OK

    logger.info(
        "window_resolved",
        start=start.isoformat(),
        end=end.isoformat(),
        date=target_date.isoformat(),
        dry_run=bool(args.dry_run),
    )

    commits, tasks, messages, statuses = _collect_all(config, start, end, logger)
    if not any(status.ok for status in statuses):
        logger.error("all_sources_failed", statuses=[status.name for status in statuses])
        return EXIT_ALL_SOURCES_FAILED

    members = _effective_members(config, commits, tasks, messages, logger)
    report = formatter.generate(
        target_date,
        members,
        commits,
        tasks,
        messages,
        statuses,
        config.team.name,
        timezone_name=config.team.timezone,
        hours_rules=HoursRules.from_config(config.hours),
    )

    outputs = _write_outputs(config, report)
    logger.info("report_generated", files=[str(path) for path in outputs])

    storage = Storage(config.report.storage_path)
    site_file = detail_file_name(report.date)
    storage.save(report, site_file)
    history = storage.list_reports(limit=HISTORY_LIMIT)
    site_paths = render_site(
        report,
        history,
        SiteConfig(directory=Path(config.report.site_dir), title=config.report.site_title),
    )
    logger.info("site_rendered", files=[str(path) for path in site_paths], entries=len(history))

    if args.dry_run:
        logger.info("push_skipped", reason="dry_run")
    else:
        _push(config, report, logger)

    logger.info(
        "run_finished",
        date=target_date.isoformat(),
        commit_count=len(commits),
        task_count=len(tasks),
        message_count=len(messages),
        members=len(report.members),
    )
    return EXIT_OK


def _collect_all(
    config: Config,
    start: datetime,
    end: datetime,
    logger: JsonLineLogger,
) -> tuple[list, list, list, list[SourceStatus]]:
    """逐数据源采集：任一源失败只标记该源，不阻断其他源（design.md §6.1）。"""

    plan = [
        (SOURCE_COMMIT, github_commit.collect),
        (SOURCE_ISSUE, github_issue.collect),
        (SOURCE_DISCUSSION, github_discussion.collect),
    ]
    results: dict[str, list] = {}
    statuses: list[SourceStatus] = []
    for name, collector in plan:
        try:
            records = collector(config, start, end)
        except CollectorError as exc:
            logger.error("source_failed", source=name, error=str(exc))
            statuses.append(SourceStatus(name=name, ok=False, count=0, error=str(exc)))
            results[name] = []
            continue
        logger.info("source_collected", source=name, count=len(records))
        statuses.append(SourceStatus(name=name, ok=True, count=len(records)))
        results[name] = records
    return (
        results[SOURCE_COMMIT],
        results[SOURCE_ISSUE],
        results[SOURCE_DISCUSSION],
        statuses,
    )


def _effective_members(
    config: Config,
    commits: list,
    tasks: list,
    messages: list,
    logger: JsonLineLogger,
) -> list[MemberConfig]:
    """按配置决定是否把未映射作者也纳入日报（默认忽略并记日志）。"""

    members = list(config.members)
    unmapped = sorted(formatter.find_unmapped(members, commits, tasks, messages))
    if not unmapped:
        return members
    if config.sources.github.include_others:
        members.extend(MemberConfig(name=identity, github_username=identity) for identity in unmapped)
        logger.info("unmapped_identities_included", identities=unmapped)
    else:
        logger.error("unmapped_identities_ignored", identities=unmapped)
    return members


def _write_outputs(config: Config, report) -> list[Path]:
    output_dir = Path(config.report.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / f"daily-report-{report.date.isoformat()}.md"
    html_path = output_dir / f"daily-report-{report.date.isoformat()}.html"
    markdown_path.write_text(report.markdown, encoding="utf-8")
    html_path.write_text(report.html, encoding="utf-8")
    return [markdown_path, html_path]


def _push(config: Config, report, logger: JsonLineLogger) -> None:
    email_config = config.notify.email
    if email_config.enabled:
        target = email_notifier.EmailTarget(
            host=email_config.host,
            port=email_config.port,
            use_ssl=email_config.use_ssl,
            sender=email_config.sender,
            username=email_config.username,
            password=email_config.password,
            recipients=email_config.recipients,
        )
        ok = email_notifier.send(report, target, logger=logger)
        logger.info("push_result", channel="email", ok=ok)
    else:
        logger.info("push_skipped", channel="email", reason="disabled")

    lark_config = config.notify.lark_bot
    if lark_config.enabled:
        ok = lark_bot.send(report, lark_bot.LarkBotTarget(webhook=lark_config.webhook), logger=logger)
        logger.info("push_result", channel="lark_bot", ok=ok)
    else:
        logger.info("push_skipped", channel="lark_bot", reason="disabled")


def _run_checks(config: Config, logger: JsonLineLogger) -> int:
    """--check：验证配置、环境变量与外部依赖连通性（不产生推送副作用）。"""

    problems: list[str] = []
    if config.required_missing_env:
        problems.append("启用功能所需的环境变量未设置: " + ", ".join(config.required_missing_env))
    logger.info("check_env", referenced=list(config.referenced_env), missing=list(config.missing_env))

    try:
        with github_commit.build_client(config) as client:
            for repo in config.repos:
                payload = client.get_json(f"/repos/{repo.owner}/{repo.name}")
                logger.info(
                    "check_github_repo",
                    repo=repo.full_name,
                    private=bool(payload.get("private")),
                    default_branch=payload.get("default_branch", ""),
                    token=client.auth_configured,
                )
    except CollectorError as exc:
        problems.append(f"GitHub 连通性检查失败: {exc}")

    email_config = config.notify.email
    if email_config.enabled:
        ok, message = email_notifier.check(
            email_notifier.EmailTarget(
                host=email_config.host,
                port=email_config.port,
                use_ssl=email_config.use_ssl,
                sender=email_config.sender,
                username=email_config.username,
                password=email_config.password,
                recipients=email_config.recipients,
            )
        )
        logger.info("check_smtp", ok=ok, detail=message)
        if not ok:
            problems.append(message)
    else:
        logger.info("check_smtp", ok=True, detail="未启用邮件推送，跳过")

    if config.notify.lark_bot.enabled and not config.notify.lark_bot.webhook:
        problems.append("飞书机器人已启用但 Webhook 为空")
    logger.info("check_lark_bot", enabled=config.notify.lark_bot.enabled)

    if problems:
        for problem in problems:
            logger.error("check_problem", detail=problem)
        return EXIT_CHECK_FAILED
    logger.info("check_passed")
    return EXIT_OK


def _resolve_window(
    args: argparse.Namespace,
    timezone: ZoneInfo,
) -> tuple[datetime, datetime, date]:
    now = datetime.now(timezone)
    if args.since or args.until:
        start = _parse_boundary(args.since, timezone) if args.since else now.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end = _parse_boundary(args.until, timezone) if args.until else now
        if end <= start:
            raise ConfigError("--until 必须晚于 --since")
        # 自定义窗口时，日报日期取窗口结束日（即"截至这一天"）
        return start, end, (end - timedelta(microseconds=1)).date()

    if args.date:
        day = date.fromisoformat(args.date)
        start = datetime.combine(day, time.min, tzinfo=timezone)
        end = start + timedelta(days=1)
        if day == now.date():
            end = now
        return start, end, day

    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, now, now.date()


def _parse_boundary(value: str, timezone: ZoneInfo) -> datetime:
    text = value.strip()
    if len(text) == 10:
        day = date.fromisoformat(text)
        return datetime.combine(day, time.min, tzinfo=timezone)
    moment = datetime.fromisoformat(text)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone)


def _is_working_day(day: date, config: Config) -> bool:
    if day in config.report.holidays:
        return False
    if config.report.skip_weekends and day.weekday() >= 5:
        return False
    return True


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="daily-report",
        description="智能日报生成器：采集 GitHub 数据，生成三段式日报与静态日报站",
    )
    parser.add_argument("--config", default="config.yaml", help="配置文件路径（默认 config.yaml）")
    parser.add_argument("--check", action="store_true", help="校验配置、环境变量与外部连通性")
    parser.add_argument("--dry-run", action="store_true", help="执行采集与生成，但不推送")
    parser.add_argument("--date", help="补跑指定日期（YYYY-MM-DD），窗口为该日整天")
    parser.add_argument("--since", help="采集窗口起点（ISO 8601 或 YYYY-MM-DD）")
    parser.add_argument("--until", help="采集窗口终点（ISO 8601 或 YYYY-MM-DD）")
    return parser.parse_args(argv)


if __name__ == "__main__":  # pragma: no cover - 手工执行入口
    raise SystemExit(main())
