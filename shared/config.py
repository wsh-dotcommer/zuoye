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

# 「数据来源」标注里的授权使用范围默认值（v2.4）
DEFAULT_ATTRIBUTION_SCOPE = "仅限团队内部日报展示"


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
class FeishuChatConfig:
    """要采集的飞书群（v2.3）：id 为 chat_id，name 仅用于日报展示。"""

    chat_id: str
    name: str


@dataclass(frozen=True)
class FeishuTaskConfig:
    """飞书任务状态同步（v2.4，只读）。

    `scope` 为 `all` 时拉取应用可见的全部任务；为 `tasklist` 时只拉
    `tasklist_guids` 里的清单（工作台任务不在默认可见范围内时用这个）。

    v2.5 起支持用户身份：`use_user_token` 为真且本地已有授权令牌时，改用
    `user_access_token` 读「我负责的」个人任务（应用身份读不到个人任务）。
    """

    enabled: bool = False
    scope: str = "all"
    tasklist_guids: tuple[str, ...] = ()
    max_tasks: int = 200
    use_user_token: bool = True
    user_token_file: str = "data/feishu-user-token.json"


@dataclass(frozen=True)
class FeishuSourceConfig:
    """飞书群消息数据源（v2.3）：只读汇总，默认关闭。"""

    enabled: bool = False
    app_id: str = ""
    app_secret: str = ""
    base_url: str = "https://open.feishu.cn"
    chats: tuple[FeishuChatConfig, ...] = ()
    retry_times: int = 3
    timeout_seconds: float = 15.0
    tasks: FeishuTaskConfig = FeishuTaskConfig()

    @property
    def any_enabled(self) -> bool:
        """群消息或任务同步任一启用，都需要 app 凭据。"""

        return self.enabled or self.tasks.enabled


@dataclass(frozen=True)
class SourcesConfig:
    github: GithubSourceConfig
    feishu: FeishuSourceConfig = FeishuSourceConfig()


@dataclass(frozen=True)
class ReportConfig:
    output_dir: Path
    site_dir: Path
    site_title: str
    storage_path: Path
    log_path: Path
    public_base_url: str = ""
    skip_weekends: bool = True
    holidays: tuple[date, ...] = ()
    workbench: bool = True
    attribution_enabled: bool = True
    attribution_scope: str = DEFAULT_ATTRIBUTION_SCOPE


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
    subject_prefix: str = ""


@dataclass(frozen=True)
class LarkBotConfig:
    enabled: bool
    webhook: str
    secret: str = ""


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


def load_config(
    path: str | Path,
    env: Mapping[str, str] | None = None,
    *,
    cwd: str | Path | None = None,
) -> Config:
    """读取并校验配置，返回强类型配置对象。

    `env` 为 None 时会自动加载 `.env`（配置文件同目录 + `cwd`，真实环境变量优先）；
    `cwd` 仅用于测试时指定查找目录。
    """

    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"配置文件不存在: {config_path}")

    environment = dict(os.environ if env is None else env)
    if env is None:
        # .env 文件（与配置文件同目录、以及当前工作目录），真实环境变量优先级更高
        file_env: dict[str, str] = {}
        base_dir = Path(cwd) if cwd is not None else Path.cwd()
        for candidate in (config_path.parent / ".env", base_dir / ".env"):
            file_env.update(load_env_file(candidate))
        environment = {**file_env, **environment}
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

    original_sources = raw.get("sources") or {}
    feishu_raw = sources_raw.get("feishu") or {}
    if not isinstance(feishu_raw, dict):
        raise ConfigError("配置项 sources.feishu 必须是映射结构")
    feishu = FeishuSourceConfig(
        enabled=bool(feishu_raw.get("enabled", False)),
        app_id=str(feishu_raw.get("app_id", "")).strip(),
        app_secret=str(feishu_raw.get("app_secret", "")).strip(),
        base_url=str(feishu_raw.get("base_url", "https://open.feishu.cn")).strip().rstrip("/")
        or "https://open.feishu.cn",
        chats=_parse_feishu_chats(feishu_raw.get("chats")),
        retry_times=int(feishu_raw.get("retry_times", 3)),
        timeout_seconds=float(feishu_raw.get("timeout_seconds", 15)),
        tasks=_parse_feishu_tasks(feishu_raw.get("tasks")),
    )
    if feishu.enabled and not feishu.chats:
        raise ConfigError("sources.feishu.enabled 为真时必须配置 chats（至少一个群）")

    attribution_raw = report_raw.get("attribution") or {}
    if not isinstance(attribution_raw, dict):
        raise ConfigError("配置项 report.attribution 必须是映射结构")
    report = ReportConfig(
        output_dir=Path(str(report_raw.get("output_dir", "output"))),
        site_dir=Path(str(report_raw.get("site_dir", "docs"))),
        site_title=str(report_raw.get("site_title", "智能日报")).strip() or "智能日报",
        storage_path=Path(str(report_raw.get("storage_path", "data/reports.sqlite3"))),
        log_path=Path(str(report_raw.get("log_path", "logs/daily-report.jsonl"))),
        public_base_url=str(report_raw.get("public_base_url", "")).strip().rstrip("/"),
        skip_weekends=bool(report_raw.get("skip_weekends", True)),
        holidays=_parse_holidays(report_raw.get("holidays")),
        workbench=bool(report_raw.get("workbench", True)),
        attribution_enabled=bool(attribution_raw.get("enabled", True)),
        attribution_scope=str(attribution_raw.get("scope", DEFAULT_ATTRIBUTION_SCOPE)).strip()
        or DEFAULT_ATTRIBUTION_SCOPE,
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
    if feishu.any_enabled and (not feishu.app_id or not feishu.app_secret):
        required_missing.extend(_placeholders(original_sources.get("feishu") or {}))

    return Config(
        team=team,
        repos=repos,
        members=members,
        sources=SourcesConfig(github=github, feishu=feishu),
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
            if value is None or value == "":
                missing.append(name)
                return ""
            return value
    return node


def load_env_file(path: str | Path) -> dict[str, str]:
    """读取 .env 文件（KEY=VALUE，支持 # 注释、引号与 export 前缀）。

    不引入第三方依赖；文件不存在时返回空字典（design.md §6.2）。
    """

    env_path = Path(path)
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    # utf-8-sig：兼容记事本等编辑器保存时带 BOM 的情况（否则第一行的键会被读坏）
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


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


def _parse_feishu_chats(value: Any) -> tuple[FeishuChatConfig, ...]:
    """解析 sources.feishu.chats（v2.3）：每项形如 `{id: oc_xxx, name: 智能日报}`。"""

    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError(f"配置项 sources.feishu.chats 类型错误，期望列表: {value!r}")
    chats: list[FeishuChatConfig] = []
    for item in value:
        if not isinstance(item, dict):
            raise ConfigError("sources.feishu.chats 的每一项必须是映射结构（id / name）")
        chat_id = str(item.get("id", "")).strip()
        if not chat_id:
            raise ConfigError("sources.feishu.chats 的每一项都必须有 id（chat_id）")
        chats.append(
            FeishuChatConfig(chat_id=chat_id, name=str(item.get("name", "")).strip() or chat_id)
        )
    return tuple(chats)


def _parse_feishu_tasks(value: Any) -> FeishuTaskConfig:
    """解析 sources.feishu.tasks（v2.4）：任务状态同步开关与同步范围。"""

    if value is None:
        return FeishuTaskConfig()
    if not isinstance(value, dict):
        raise ConfigError("配置项 sources.feishu.tasks 必须是映射结构")

    raw_scope = str(value.get("scope", "all")).strip().lower() or "all"
    tasklist_guids = _as_str_tuple(value.get("tasklist_guids"))
    if raw_scope not in ("all", "tasklist"):
        raise ConfigError(
            f"sources.feishu.tasks.scope 只支持 all / tasklist，实际为: {raw_scope!r}"
        )

    config = FeishuTaskConfig(
        enabled=bool(value.get("enabled", False)),
        scope=raw_scope,
        tasklist_guids=tasklist_guids,
        max_tasks=int(value.get("max_tasks", 200)),
        use_user_token=bool(value.get("use_user_token", True)),
        user_token_file=str(
            value.get("user_token_file", "data/feishu-user-token.json")
        ).strip()
        or "data/feishu-user-token.json",
    )
    if config.max_tasks <= 0:
        raise ConfigError("sources.feishu.tasks.max_tasks 必须大于 0")
    if config.enabled and config.scope == "tasklist" and not config.tasklist_guids:
        raise ConfigError(
            "sources.feishu.tasks.scope 为 tasklist 时必须配置 tasklist_guids（至少一个清单）"
        )
    return config


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
        subject_prefix=str(email_raw.get("subject_prefix", "")).strip(),
    )
    lark_bot = LarkBotConfig(
        enabled=bool(lark_raw.get("enabled", False)),
        webhook=str(lark_raw.get("webhook", "")).strip(),
        secret=str(lark_raw.get("secret", "")).strip(),
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
