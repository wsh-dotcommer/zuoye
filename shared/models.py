"""跨模块共享的数据模型（design.md §3）。

模型只承载语义，不绑定实现：采集器产出它们，生成层消费它们。
"""

from dataclasses import dataclass, field
from datetime import date, datetime

# 数据源标识（SourceStatus.name）
SOURCE_COMMIT = "github_commit"
SOURCE_ISSUE = "github_issue"
SOURCE_DISCUSSION = "github_discussion"

SOURCE_LABELS = {
    SOURCE_COMMIT: "代码提交",
    SOURCE_ISSUE: "任务进展",
    SOURCE_DISCUSSION: "协作沟通",
}

# 任务状态标签（TaskRecord.status_from / status_to）
STATUS_NEW = "新建"
STATUS_IN_PROGRESS = "进行中"
STATUS_DONE = "已完成"

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


@dataclass(frozen=True)
class TaskRecord:
    """任务变更记录（由 GitHub Issue 状态流转推导）。"""

    assignee: str
    title: str
    status_from: str
    status_to: str
    updated_at: datetime


@dataclass(frozen=True)
class MessageRecord:
    """协作讨论记录。"""

    sender: str
    content: str
    timestamp: datetime
    source: str


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
