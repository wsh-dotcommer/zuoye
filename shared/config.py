"""配置读取与校验（design.md §2、§6）。

配置文件为 YAML，密钥一律写成 ``${ENV_NAME}`` 占位符，运行时从环境变量解析，
严禁在配置或代码中硬编码凭据（design.md §6.2）。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import yaml

from shared.errors import ConfigError

_PLACEHOLDER = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


@dataclass(frozen=True)
class TeamConfig:
    name: str
    leader_email: str
    timezone: str


@dataclass(frozen=True)
class RepoConfig:
    owner: str
    name: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass(frozen=True)
class MemberConfig:
    name: str
    github_username: str
    github_emails: tuple[str, ...] = ()

    def matches(self, identity: str) -> bool:
        """判断某个采集到的身份（GitHub 用户名或邮箱）是否属于本成员。"""

        target = (identity or "").strip().lower()
        if not target:
            return False
        if target == self.github_username.strip().lower():
            return True
        return target in {email.strip().lower() for email in self.github_emails}


@dataclass(frozen=True)
class GithubSourceConfig:
    token: str = ""
    include_others: bool = False
    exclude_bots: bool = True
    keywords: tuple[str, ...] = ()
    sensitive_keywords: tuple[str, ...] = ()
    max_commit_details: int = 100
    max_issue_timelines: int = 50
    per_page: int = 100
    retry_times: int = 3
    retry_interval_seconds: float = 5.0
    rate_limit_max_wait_seconds: float = 300.0
    timeout_seconds: float = 15.0


@dataclass(frozen=True)
class SourcesConfig:
    github: GithubSourceConfig


@dataclass(frozen=True)
class ReportConfig:
    output_dir: Path
    site_dir: Path
    site_title: str
    storage_path: Path
    log_path: Path
    skip_weekends: bool = True
    holidays: tuple[date, ...] = ()


@dataclass(frozen=True)
class HoursConfig:
    """工时推导参数（design.md §4.2、§6.4，v1.1）。"""

    enabled: bool = True
    gap_minutes: int = 60
    wrap_up_hours: float = 0.5
    rounding_hours: float = 0.5
    daily_cap_hours: float = 12.0


@dataclass(frozen=True)
class EmailConfig:
    enabled: bool
    host: str
    port: int
    use_ssl: bool
    sender: str
    username: str
    password: str
    recipients: tuple[str, ...]


@dataclass(frozen=True)
class LarkBotConfig:
    enabled: bool
    webhook: str


@dataclass(frozen=True)
class NotifyConfig:
    email: EmailConfig
    lark_bot: LarkBotConfig


@dataclass(frozen=True)
class Config:
    team: TeamConfig
    repos: tuple[RepoConfig, ...]
    members: tuple[MemberConfig, ...]
    sources: SourcesConfig
    hours: HoursConfig
    report: ReportConfig
    notify: NotifyConfig
    path: Path
    referenced_env: tuple[str, ...] = field(default=())
    missing_env: tuple[str, ...] = field(default=())
    required_missing_env: tuple[str, ...] = field(default=())


def load_config(path: str | Path, env: Mapping[str, str] | None = None) -> Config:
    """读取并校验配置，返回强类型配置对象。"""

    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"配置文件不存在: {config_path}")

    environment = dict(os.environ if env is None else env)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - YAML 语法错误分支
        raise ConfigError(f"配置文件解析失败: {config_path} ({exc})") from exc
    if not isinstance(raw, dict):
        raise ConfigError("配置文件根节点必须是映射（key: value）结构")

    referenced: list[str] = []
    missing: list[str] = []
    resolved = _resolve_placeholders(raw, environment, referenced, missing)

    team_raw = _require_mapping(resolved, "team")
    repos = _parse_repos(resolved)
    members = _parse_members(resolved)
    sources_raw = _require_mapping(resolved, "sources")
    report_raw = _require_mapping(resolved, "report")
    notify_raw = resolved.get("notify") or {}
    if not isinstance(notify_raw, dict):
        raise ConfigError("配置项 notify 必须是映射结构")

    team = TeamConfig(
        name=_require_str(team_raw, "team.name"),
        leader_email=str(team_raw.get("leader_email", "")).strip(),
        timezone=str(team_raw.get("timezone", "Asia/Shanghai")).strip() or "Asia/Shanghai",
    )

    github_raw = sources_raw.get("github") or {}
    if not isinstance(github_raw, dict):
        raise ConfigError("配置项 sources.github 必须是映射结构")
    github = GithubSourceConfig(
        token=str(github_raw.get("token", "")).strip(),
        include_others=bool(github_raw.get("include_others", False)),
        exclude_bots=bool(github_raw.get("exclude_bots", True)),
        keywords=_as_str_tuple(github_raw.get("keywords")),
        sensitive_keywords=_as_str_tuple(github_raw.get("sensitive_keywords")),
        max_commit_details=int(github_raw.get("max_commit_details", 100)),
        max_issue_timelines=int(github_raw.get("max_issue_timelines", 50)),
        per_page=int(github_raw.get("per_page", 100)),
        retry_times=int(github_raw.get("retry_times", 3)),
        retry_interval_seconds=float(github_raw.get("retry_interval_seconds", 5)),
        rate_limit_max_wait_seconds=float(github_raw.get("rate_limit_max_wait_seconds", 300)),
        timeout_seconds=float(github_raw.get("timeout_seconds", 15)),
    )

    report = ReportConfig(
        output_dir=Path(str(report_raw.get("output_dir", "output"))),
        site_dir=Path(str(report_raw.get("site_dir", "docs"))),
        site_title=str(report_raw.get("site_title", "智能日报")).strip() or "智能日报",
        storage_path=Path(str(report_raw.get("storage_path", "data/reports.sqlite3"))),
        log_path=Path(str(report_raw.get("log_path", "logs/daily-report.jsonl"))),
        skip_weekends=bool(report_raw.get("skip_weekends", True)),
        holidays=_parse_holidays(report_raw.get("holidays")),
    )

    hours = _parse_hours(resolved.get("hours"))

    original_notify = raw.get("notify") or {}
    notify = _parse_notify(notify_raw, original_notify)
    # 只有"已启用功能"所依赖的环境变量缺失才算致命问题；
    # GITHUB_TOKEN 这类可选凭据缺失只做提示（匿名访问依然可用）。
    required_missing: list[str] = []
    if notify.email.enabled and (not notify.email.username or not notify.email.password):
        required_missing.extend(_placeholders(original_notify.get("email") or {}))
    if notify.lark_bot.enabled and not notify.lark_bot.webhook:
        required_missing.extend(_placeholders(original_notify.get("lark_bot") or {}))

    return Config(
        team=team,
        repos=repos,
        members=members,
        sources=SourcesConfig(github=github),
        hours=hours,
        report=report,
        notify=notify,
        path=config_path,
        referenced_env=tuple(dict.fromkeys(referenced)),
        missing_env=tuple(dict.fromkeys(missing)),
        required_missing_env=tuple(
            dict.fromkeys(name for name in required_missing if name in set(missing))
        ),
    )


def build_member_lookup(config: Config) -> dict[str, MemberConfig]:
    """身份 → 成员 的查找表，键统一小写。"""

    lookup: dict[str, MemberConfig] = {}
    for member in config.members:
        lookup[member.github_username.strip().lower()] = member
        for email in member.github_emails:
            lookup[email.strip().lower()] = member
    return lookup


def _resolve_placeholders(
    node: Any,
    env: Mapping[str, str],
    referenced: list[str],
    missing: list[str],
) -> Any:
    if isinstance(node, dict):
        return {key: _resolve_placeholders(value, env, referenced, missing) for key, value in node.items()}
    if isinstance(node, list):
        return [_resolve_placeholders(item, env, referenced, missing) for item in node]
    if isinstance(node, str):
        match = _PLACEHOLDER.match(node.strip())
        if match:
            name = match.group(1)
            referenced.append(name)
            value = env.get(name)
            if value is None:
                missing.append(name)
                return ""
            return value
    return node


def _require_mapping(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"缺少必填配置块: {key}")
    return value


def _placeholders(node: Any) -> list[str]:
    """收集某个配置子树里出现的 ``${ENV}`` 变量名。"""

    if isinstance(node, dict):
        names: list[str] = []
        for value in node.values():
            names.extend(_placeholders(value))
        return names
    if isinstance(node, list):
        names = []
        for item in node:
            names.extend(_placeholders(item))
        return names
    if isinstance(node, str):
        match = _PLACEHOLDER.match(node.strip())
        if match:
            return [match.group(1)]
    return []


def _require_str(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key.split(".", 1)[-1])
    text = "" if value is None else str(value).strip()
    if not text:
        raise ConfigError(f"缺少必填配置项: {key}")
    return text


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    raise ConfigError(f"配置项类型错误，期望字符串列表: {value!r}")


def _parse_repos(raw: Mapping[str, Any]) -> tuple[RepoConfig, ...]:
    items = raw.get("repos")
    if not isinstance(items, list) or not items:
        raise ConfigError("缺少必填配置项: repos（至少一个仓库）")
    repos: list[RepoConfig] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ConfigError(f"repos[{index}] 必须是映射结构")
        owner = str(item.get("owner", "")).strip()
        name = str(item.get("name", "")).strip()
        if not owner or not name:
            raise ConfigError(f"repos[{index}] 缺少 owner 或 name")
        repos.append(RepoConfig(owner=owner, name=name))
    return tuple(repos)


def _parse_members(raw: Mapping[str, Any]) -> tuple[MemberConfig, ...]:
    items = raw.get("members")
    if not isinstance(items, list) or not items:
        raise ConfigError("缺少必填配置项: members（至少一名成员）")
    members: list[MemberConfig] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ConfigError(f"members[{index}] 必须是映射结构")
        name = str(item.get("name", "")).strip()
        username = str(item.get("github_username", "")).strip()
        if not name or not username:
            raise ConfigError(f"members[{index}] 缺少 name 或 github_username")
        members.append(
            MemberConfig(
                name=name,
                github_username=username,
                github_emails=_as_str_tuple(item.get("github_emails")),
            )
        )
    return tuple(members)


def _parse_holidays(value: Any) -> tuple[date, ...]:
    if not value:
        return ()
    if not isinstance(value, list):
        raise ConfigError("配置项 report.holidays 必须是日期字符串列表，如 [2026-10-01]")
    holidays: list[date] = []
    for item in value:
        try:
            holidays.append(date.fromisoformat(str(item).strip()))
        except ValueError as exc:
            raise ConfigError(f"report.holidays 中的日期格式非法: {item!r}（应为 YYYY-MM-DD）") from exc
    return tuple(holidays)


def _parse_hours(raw: Any) -> HoursConfig:
    """解析工时推导参数；缺省时使用默认值（design.md §4.2）。"""

    if raw is None:
        return HoursConfig()
    if not isinstance(raw, dict):
        raise ConfigError("配置项 hours 必须是映射结构")

    config = HoursConfig(
        enabled=bool(raw.get("enabled", True)),
        gap_minutes=int(raw.get("gap_minutes", 60)),
        wrap_up_hours=float(raw.get("wrap_up_hours", 0.5)),
        rounding_hours=float(raw.get("rounding_hours", 0.5)),
        daily_cap_hours=float(raw.get("daily_cap_hours", 12)),
    )
    if config.gap_minutes <= 0:
        raise ConfigError("配置项 hours.gap_minutes 必须大于 0")
    if config.wrap_up_hours < 0:
        raise ConfigError("配置项 hours.wrap_up_hours 不能为负数")
    if config.rounding_hours <= 0:
        raise ConfigError("配置项 hours.rounding_hours 必须大于 0")
    if config.daily_cap_hours <= 0:
        raise ConfigError("配置项 hours.daily_cap_hours 必须大于 0")
    return config


def _parse_notify(raw: Mapping[str, Any], original: Mapping[str, Any] | None = None) -> NotifyConfig:
    email_raw = raw.get("email") or {}
    lark_raw = raw.get("lark_bot") or {}
    original_lark = (original or {}).get("lark_bot") or {}
    if not isinstance(email_raw, dict) or not isinstance(lark_raw, dict):
        raise ConfigError("配置项 notify.email / notify.lark_bot 必须是映射结构")

    email = EmailConfig(
        enabled=bool(email_raw.get("enabled", False)),
        host=str(email_raw.get("host", "")).strip(),
        port=int(email_raw.get("port", 465)),
        use_ssl=bool(email_raw.get("use_ssl", True)),
        sender=str(email_raw.get("sender", "")).strip(),
        username=str(email_raw.get("username", "")).strip(),
        password=str(email_raw.get("password", "")).strip(),
        recipients=_as_str_tuple(email_raw.get("recipients")),
    )
    lark_bot = LarkBotConfig(
        enabled=bool(lark_raw.get("enabled", False)),
        webhook=str(lark_raw.get("webhook", "")).strip(),
    )

    if email.enabled:
        if not email.host:
            raise ConfigError("notify.email.enabled 为真时必须配置 host")
        if not email.sender:
            raise ConfigError("notify.email.enabled 为真时必须配置 sender")
        if not email.recipients:
            raise ConfigError("notify.email.enabled 为真时必须配置 recipients")
    if lark_bot.enabled and not lark_bot.webhook and not _is_placeholder_text(original_lark.get("webhook")):
        raise ConfigError("notify.lark_bot.enabled 为真时必须配置 webhook（建议写成 ${LARK_BOT_WEBHOOK}）")

    return NotifyConfig(email=email, lark_bot=lark_bot)


def _is_placeholder_text(value: Any) -> bool:
    """判断原始配置值是否为 ``${ENV}`` 占位符（未解析时留给 --check 报告）。"""

    return isinstance(value, str) and _PLACEHOLDER.match(value.strip()) is not None
