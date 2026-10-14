"""跨模块共享的数据模型（design.md §3）。

模型只承载语义，不绑定实现：采集器产出它们，生成层消费它们。
"""

from dataclasses import dataclass, field
from datetime import date, datetime

# 数据源标识（SourceStatus.name）
SOURCE_COMMIT = "github_commit"
SOURCE_ISSUE = "github_issue"
SOURCE_DISCUSSION = "github_discussion"
SOURCE_FEISHU = "feishu_message"
SOURCE_FEISHU_TASK = "feishu_task"

SOURCE_LABELS = {
    SOURCE_COMMIT: "代码提交",
    SOURCE_ISSUE: "任务进展",
    SOURCE_DISCUSSION: "协作沟通",
    SOURCE_FEISHU: "飞书消息",
    SOURCE_FEISHU_TASK: "飞书任务",
}

# 任务状态标签（TaskRecord.status_from / status_to）
STATUS_NEW = "新建"
STATUS_IN_PROGRESS = "进行中"
STATUS_DONE = "已完成"
# 飞书任务三态（FeishuTaskRecord.status，v2.4）：与上面的 Issue 流转标签并存，
# 「未开始」只描述飞书任务的当前状态，不参与 GitHub Issue 的状态流转。
STATUS_NOT_STARTED = "未开始"

# 飞书任务三态的固定展示顺序（进行中 → 未开始 → 已完成）
TASK_STATUS_ORDER = (STATUS_IN_PROGRESS, STATUS_NOT_STARTED, STATUS_DONE)

# 工时记录状态（WorkHoursRecord.state，v1.1）
HOURS_OK = "ok"
HOURS_EMPTY = "empty"
HOURS_UNAVAILABLE = "unavailable"

# 工时口径说明：任何对外呈现都必须带上（design.md §6.4）
WORK_HOURS_NOTE = "按提交时间推导，非真实考勤"


@dataclass(frozen=True)
class CommitRecord:
    """代码提交记录。"""

    author: str
    message: str
    timestamp: datetime
    repo: str
    additions: int
    deletions: int
    files_changed: int
    files: tuple[str, ...] = ()
    sha: str = ""
    url: str = ""


@dataclass(frozen=True)
class TaskRecord:
    """任务变更记录（由 GitHub Issue 状态流转推导）。"""

    assignee: str
    title: str
    status_from: str
    status_to: str
    updated_at: datetime
    number: int = 0
    url: str = ""
    labels: tuple[str, ...] = ()
    comment_count: int = 0


@dataclass(frozen=True)
class MessageRecord:
    """协作讨论记录。"""

    sender: str
    content: str
    timestamp: datetime
    source: str
    url: str = ""


@dataclass(frozen=True)
class WorkHoursRecord:
    """工时记录（v1.1）：由提交时间按会话法推导得出。"""

    hours: float = 0.0
    session_count: int = 0
    commit_count: int = 0
    state: str = HOURS_EMPTY
    detail: str = ""

    @property
    def available(self) -> bool:
        return self.state != HOURS_UNAVAILABLE


@dataclass(frozen=True)
class ChatSummaryRecord:
    """飞书群消息汇总（v2.3）。

    只承载"条数与发言人数"两件事：正文在采集器里就地丢弃，
    既不进模型、也不进产物与日志，避免群聊内容流进公开站点。
    """

    chat_name: str
    message_count: int
    speaker_count: int


@dataclass(frozen=True)
class ReportStats:
    """一期日报的结构化统计（v2.3），用于跨期对比与趋势，避免解析 Markdown。"""

    date: date
    commit_count: int = 0
    task_count: int = 0
    message_count: int = 0
    chat_message_count: int = 0
    total_hours: float = 0.0


@dataclass(frozen=True)
class DataSourceRef:
    """「数据来源」标注里的一个数据源全称（v2.4）。

    `label` 是类别（如 `GitHub 仓库`），`full_name` 是具体对象
    （如 `wsh-dotcommer/zuoye`），两者拼接即为对外标注里的数据源全称。
    """

    label: str
    full_name: str = ""

    def render(self) -> str:
        """拼成标注里的一段：`GitHub 仓库 wsh-dotcommer/zuoye`。"""

        if self.full_name:
            return f"{self.label} {self.full_name}"
        return self.label


@dataclass(frozen=True)
class FeishuTaskRecord:
    """飞书工作台任务的当前状态快照（v2.4，只读）。

    与 `TaskRecord` 的区别：`TaskRecord` 是 GitHub Issue 的"状态流转"
    （谁在哪天把什么从 A 推到了 B）；本记录是飞书任务的"此刻状态"。
    """

    guid: str
    summary: str
    status: str = STATUS_IN_PROGRESS
    due: date | None = None
    completed_at: datetime | None = None
    updated_at: datetime | None = None
    url: str = ""


@dataclass
class MemberReport:
    """成员日报段落。"""

    name: str
    github_username: str
    commits: list[CommitRecord] = field(default_factory=list)
    tasks: list[TaskRecord] = field(default_factory=list)
    messages: list[MessageRecord] = field(default_factory=list)
    work_hours: WorkHoursRecord | None = None


@dataclass(frozen=True)
class SourceStatus:
    """单个数据源的采集状态。"""

    name: str
    ok: bool
    count: int = 0
    error: str = ""

    @property
    def label(self) -> str:
        return SOURCE_LABELS.get(self.name, self.name)


@dataclass
class DailyReport:
    """每日报告（含 Markdown 与 HTML 两种形态）。"""

    date: date
    team_name: str
    members: list[MemberReport]
    generated_at: datetime
    markdown: str = ""
    html: str = ""
    source_statuses: list[SourceStatus] = field(default_factory=list)
    total_hours: float = 0.0
    member_count: int = 0
    commit_count: int = 0
    task_count: int = 0
    message_count: int = 0
    chat_message_count: int = 0
    recent_stats: list[ReportStats] = field(default_factory=list)
    chat_summaries: list[ChatSummaryRecord] = field(default_factory=list)
    feishu_tasks: list[FeishuTaskRecord] = field(default_factory=list)
    attribution: str = ""
