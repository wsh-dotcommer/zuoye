"""GitHub Issue 采集：把状态流转映射为「任务进展」（design.md §4.1，Task 4）。

接口契约：
    collect(config, start, end) -> list[TaskRecord]
"""

from __future__ import annotations

from datetime import datetime

from shared.config import Config, RepoConfig
from shared.errors import CollectorError
from shared.http import GitHubClient, parse_timestamp, to_github_time
from shared.logger import JsonLineLogger, build_logger
from shared.models import STATUS_DONE, STATUS_IN_PROGRESS, STATUS_NEW, TaskRecord


def build_client(config: Config) -> GitHubClient:
    """构造 GitHub 客户端；测试通过替换本函数注入 MockTransport。"""

    github = config.sources.github
    return GitHubClient(
        token=github.token,
        retry_times=github.retry_times,
        retry_interval=github.retry_interval_seconds,
        rate_limit_max_wait=github.rate_limit_max_wait_seconds,
        timeout=github.timeout_seconds,
        per_page=github.per_page,
        logger=build_logger(config.report.log_path, echo=False),
    )


def collect(config: Config, start: datetime, end: datetime) -> list[TaskRecord]:
    """采集采集窗口内发生状态变更的 Issue 列表。"""

    logger = build_logger(config.report.log_path, echo=False)
    records: list[TaskRecord] = []
    timeline_budget = config.sources.github.max_issue_timelines

    with build_client(config) as client:
        for repo in config.repos:
            for issue in client.paginate(
                f"/repos/{repo.owner}/{repo.name}/issues",
                {
                    "state": "all",
                    "since": to_github_time(start),
                    "sort": "updated",
                    "direction": "desc",
                },
            ):
                if "pull_request" in issue:
                    continue
                use_timeline = timeline_budget > 0
                if use_timeline:
                    timeline_budget -= 1
                change = _state_change(client, repo, issue, start, end, logger, use_timeline=use_timeline)
                if change is None:
                    continue
                status_from, status_to, moment, actor = change
                records.append(
                    TaskRecord(
                        assignee=_resolve_assignee(issue, actor),
                        title=str(issue.get("title", "")).strip(),
                        status_from=status_from,
                        status_to=status_to,
                        updated_at=moment,
                    )
                )
    return records


def _state_change(
    client: GitHubClient,
    repo: RepoConfig,
    issue: dict,
    start: datetime,
    end: datetime,
    logger: JsonLineLogger,
    *,
    use_timeline: bool = True,
) -> tuple[str, str, datetime, str] | None:
    number = int(issue.get("number", 0))
    moment = None
    if use_timeline:
        moment = _timeline_change(client, repo, number, start, end, logger)
    else:
        # 超出 timeline 预算：退化为字段推断，仍受 rate limit 保护（design.md §4.1）
        logger.error("issue_timeline_budget_exhausted", repo=repo.full_name, number=number)
    if moment is not None:
        return moment
    return _field_fallback(issue, start, end)


def _timeline_change(
    client: GitHubClient,
    repo: RepoConfig,
    number: int,
    start: datetime,
    end: datetime,
    logger: JsonLineLogger,
) -> tuple[str, str, datetime, str] | None:
    """通过 timeline 事件推导状态流转；取窗口内最后一个状态事件。"""

    try:
        events = client.get_json(
            f"/repos/{repo.owner}/{repo.name}/issues/{number}/timeline",
            {"per_page": client.per_page},
        )
    except CollectorError as exc:
        # timeline 不可用时退化为字段推断，但必须留痕（design.md §6.1）
        logger.error("issue_timeline_unavailable", repo=repo.full_name, number=number, error=str(exc))
        return None

    if not isinstance(events, list):
        return None

    matched: list[tuple[str, str, datetime, str]] = []
    for event in events:
        name = event.get("event")
        raw_time = event.get("created_at")
        if not name or not raw_time:
            continue
        moment = parse_timestamp(str(raw_time))
        if not (start <= moment < end):
            continue
        actor = str((event.get("actor") or {}).get("login", ""))
        if name == "closed":
            matched.append((STATUS_IN_PROGRESS, STATUS_DONE, moment, actor))
        elif name == "reopened":
            matched.append((STATUS_DONE, STATUS_IN_PROGRESS, moment, actor))
    if not matched:
        return None
    return max(matched, key=lambda item: item[2])


def _field_fallback(
    issue: dict,
    start: datetime,
    end: datetime,
) -> tuple[str, str, datetime, str] | None:
    """timeline 缺失时的兜底推断：关闭时间 / 创建时间。"""

    author = str((issue.get("user") or {}).get("login", ""))
    closed_at = issue.get("closed_at")
    if closed_at:
        moment = parse_timestamp(str(closed_at))
        if start <= moment < end:
            closer = str((issue.get("closed_by") or {}).get("login", "")) or author
            return STATUS_IN_PROGRESS, STATUS_DONE, moment, closer
    created_at = issue.get("created_at")
    if created_at and str(issue.get("state")) == "open":
        moment = parse_timestamp(str(created_at))
        if start <= moment < end:
            return STATUS_NEW, STATUS_IN_PROGRESS, moment, author
    return None


def _resolve_assignee(issue: dict, actor: str) -> str:
    """负责人缺失时退化为状态变更执行者 / Issue 创建者（design.md §3）。"""

    assigned = str((issue.get("assignee") or {}).get("login", ""))
    if assigned:
        return assigned
    return actor or str((issue.get("user") or {}).get("login", ""))
