"""GitHub 协作讨论采集（design.md §4.1，Task 5）。

数据来源：Issue/PR 对话评论（issues/comments）与 PR 行内评审评论（pulls/comments）。
接口契约：
    collect(config, start, end) -> list[MessageRecord]
"""

from __future__ import annotations

from datetime import datetime

from shared.config import Config, GithubSourceConfig, RepoConfig
from shared.filters import is_bot
from shared.http import GitHubClient, parse_timestamp, to_github_time
from shared.logger import JsonLineLogger, build_logger
from shared.models import MessageRecord


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


def collect(config: Config, start: datetime, end: datetime) -> list[MessageRecord]:
    """采集采集窗口内、通过关键词与敏感词过滤的讨论记录。"""

    logger = build_logger(config.report.log_path, echo=False)
    github = config.sources.github
    records: list[MessageRecord] = []

    with build_client(config) as client:
        for repo in config.repos:
            records.extend(
                _collect_endpoint(
                    client,
                    repo,
                    "/issues/comments",
                    start,
                    end,
                    github,
                    logger,
                    source_builder=_issue_source,
                )
            )
            records.extend(
                _collect_endpoint(
                    client,
                    repo,
                    "/pulls/comments",
                    start,
                    end,
                    github,
                    logger,
                    source_builder=_pull_source,
                )
            )
    return records


def _collect_endpoint(
    client: GitHubClient,
    repo: RepoConfig,
    endpoint: str,
    start: datetime,
    end: datetime,
    github: GithubSourceConfig,
    logger: JsonLineLogger,
    *,
    source_builder,
) -> list[MessageRecord]:
    path = f"/repos/{repo.owner}/{repo.name}{endpoint}"
    records: list[MessageRecord] = []
    skipped = 0
    skipped_bots = 0
    for comment in client.paginate(path, {"since": to_github_time(start), "sort": "created", "direction": "asc"}):
        timestamp = parse_timestamp(str(comment.get("created_at", "")))
        if not (start <= timestamp < end):
            continue
        user = comment.get("user") or {}
        if github.exclude_bots and is_bot(str(user.get("login", "")), str(user.get("type", ""))):
            skipped_bots += 1
            continue
        content = str(comment.get("body") or "").strip()
        if not content:
            continue
        if not passes_filters(content, github):
            skipped += 1
            continue
        records.append(
            MessageRecord(
                sender=str(user.get("login", "")),
                content=content,
                timestamp=timestamp,
                source=source_builder(repo, comment),
            )
        )
    if skipped:
        logger.info("discussion_filtered", repo=repo.full_name, endpoint=endpoint, skipped=skipped)
    if skipped_bots:
        logger.info("discussion_bots_skipped", repo=repo.full_name, endpoint=endpoint, skipped=skipped_bots)
    return records


def passes_filters(content: str, github: GithubSourceConfig) -> bool:
    """敏感词黑名单优先，其次关键词白名单（白名单为空表示不过滤）。"""

    lowered = content.lower()
    if any(word.lower() in lowered for word in github.sensitive_keywords):
        return False
    if not github.keywords:
        return True
    return any(word.lower() in lowered for word in github.keywords)


def _issue_source(repo: RepoConfig, comment: dict) -> str:
    url = str(comment.get("issue_url") or "")
    number = url.rstrip("/").rsplit("/", 1)[-1] if url else "?"
    return f"{repo.full_name} #{number}"


def _pull_source(repo: RepoConfig, comment: dict) -> str:
    number = comment.get("pull_request_review_id") or comment.get("id") or "?"
    url = str(comment.get("html_url") or "").split("#", 1)[0]
    if "/pull/" in url:
        number = url.split("/pull/", 1)[1].split("/", 1)[0]
    return f"{repo.full_name} PR #{number}"
