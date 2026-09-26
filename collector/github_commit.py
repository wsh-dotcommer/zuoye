"""GitHub 提交采集（design.md §4.1，Task 3）。

接口契约：
    collect(config, start, end) -> list[CommitRecord]
"""

from __future__ import annotations

from datetime import datetime

from shared.config import Config, RepoConfig
from shared.errors import CollectorError
from shared.filters import is_bot
from shared.http import GitHubClient, parse_timestamp, to_github_time
from shared.logger import JsonLineLogger, build_logger
from shared.models import CommitRecord


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


def collect(config: Config, start: datetime, end: datetime) -> list[CommitRecord]:
    """采集采集窗口内的提交记录（含每条提交的变更统计）。"""

    logger = build_logger(config.report.log_path, echo=False)
    github = config.sources.github
    records: list[CommitRecord] = []
    details_fetched = 0
    bots_skipped = 0

    with build_client(config) as client:
        for repo in config.repos:
            try:
                items = list(
                    client.paginate(
                        f"/repos/{repo.owner}/{repo.name}/commits",
                        {"since": to_github_time(start), "until": to_github_time(end)},
                    )
                )
            except CollectorError as exc:
                if "empty" in str(exc).lower():
                    # 空仓库按"无提交"处理，而不是数据源失败（design.md §6.1）
                    logger.error("repo_empty", repo=repo.full_name)
                    continue
                raise
            for item in items:
                if github.exclude_bots and is_bot(str((item.get("author") or {}).get("login", ""))):
                    bots_skipped += 1
                    continue
                moment = _commit_time(item)
                if not (start <= moment < end):
                    continue
                additions = deletions = files_changed = 0
                if details_fetched < github.max_commit_details:
                    details_fetched += 1
                    additions, deletions, files_changed = _fetch_stats(client, repo, item, logger)
                else:
                    logger.error(
                        "commit_details_limit_reached",
                        repo=repo.full_name,
                        limit=github.max_commit_details,
                    )
                records.append(
                    CommitRecord(
                        author=_commit_author(item),
                        message=_first_line(item.get("commit", {}).get("message", "")),
                        timestamp=moment,
                        repo=repo.full_name,
                        additions=additions,
                        deletions=deletions,
                        files_changed=files_changed,
                    )
                )
    if bots_skipped:
        logger.info("commits_bots_skipped", skipped=bots_skipped)
    return records


def _fetch_stats(
    client: GitHubClient,
    repo: RepoConfig,
    item: dict,
    logger: JsonLineLogger,
) -> tuple[int, int, int]:
    sha = item.get("sha", "")
    if not sha:
        return 0, 0, 0
    try:
        detail = client.get_json(f"/repos/{repo.owner}/{repo.name}/commits/{sha}")
    except CollectorError as exc:
        # 单条提交统计失败不影响整条流水线，但必须留痕（design.md §6.1）
        logger.error("commit_stats_unavailable", repo=repo.full_name, sha=sha, error=str(exc))
        return 0, 0, 0
    stats = detail.get("stats") or {}
    files = detail.get("files") or []
    return (
        int(stats.get("additions", 0)),
        int(stats.get("deletions", 0)),
        len(files),
    )


def _commit_time(item: dict) -> datetime:
    payload = item.get("commit") or {}
    author = payload.get("author") or payload.get("committer") or {}
    return parse_timestamp(author.get("date", ""))


def _commit_author(item: dict) -> str:
    """优先取 GitHub 用户名；缺失时退化为提交邮箱（design.md §3）。"""

    login = (item.get("author") or {}).get("login")
    if login:
        return str(login)
    payload = item.get("commit") or {}
    author = payload.get("author") or payload.get("committer") or {}
    return str(author.get("email") or author.get("name") or "")


def _first_line(message: str) -> str:
    return (message or "").strip().splitlines()[0] if (message or "").strip() else ""
