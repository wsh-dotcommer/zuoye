# 智能日报生成器 — 架构设计

规范版本：v1.1（与 `specs/proposal.md` 对应）

## 变更记录

| 版本 | 变更类型 | 内容 |
| --- | --- | --- |
| v1.0 | 首版 | 管道式架构、三类 GitHub 采集器、三段式日报、静态站、SQLite 历史 |
| v1.1 | 需求变更（由 proposal.md v1.1 传导） | §2 生成层新增 `hours.py`；§3 新增 `WorkHoursRecord` 并扩展 `MemberReport`/`DailyReport`；§4.2 新增 `derive()` 契约并扩展 `generate()`；§5 新增 ADR-006；§6 新增口径与诚实性约束 |

## 1. 系统架构

采用**管道式架构**：

```txt
                 ┌────────────────── 共享基础层（shared/）──────────────────┐
                 │ config 配置校验 · logger JSON 日志 · errors 异常体系      │
                 │ http 重试与限流策略 · models 数据模型 · storage SQLite   │
                 └──────────────────────────────────────────────────────────┘
                                          ▲ 被各层使用
   ┌───────────────┐   ┌───────────────┐   ┌───────────────┐
   │ 采集层        │   │ 生成层        │   │ 推送层        │
   │ collector/    │   │ generator/    │   │ notifier/     │
   │  commit       │──▶│  formatter    │──▶│  email        │
   │  issue        │   │  template     │   │  lark_bot     │
   │  discussion   │   │  site（静态站）│   └───────────────┘
   └───────────────┘   └───────────────┘
            ▲                  │
            │                  ▼
     GitHub REST API     output/*.md|html + docs/*.html + SQLite

                        编排入口：main.py（采集→聚合→生成→站点→推送）
```

数据流：`main.py` 按窗口调用三个采集器 → 归一为记录列表 → 生成层按成员聚合、渲染 Markdown/HTML/站点 → 存储层落库 → 推送层按配置发送。任一层失败只影响自身分支，不阻断整条管道。

## 2. 模块职责

| 模块 | 文件 | 负责 | 不负责 |
| --- | --- | --- | --- |
| collector/ | `github_commit.py`<br>`github_issue.py`<br>`github_discussion.py` | 从 GitHub REST API 获取原始数据：提交记录、Issue 状态变更、PR/Issue 讨论；做字段标准化与配置级过滤 | 不做日报排版、不做成员聚合决策、不做推送 |
| generator/ | `formatter.py`<br>`hours.py`<br>`template.py`<br>`site.py` | 按成员聚合原始记录、编排日报板块、从提交时间推导工时（会话法）、生成 Markdown 与 HTML、渲染静态日报站（索引页+详情页） | 不做数据采集、不调用外部 API、不做推送 |
| notifier/ | `email.py`<br>`lark_bot.py` | 将日报推送给目标：SMTP 邮件发送、飞书群机器人消息推送 | 不做数据处理、不做日报生成、不做数据采集 |
| shared/ | `config.py`<br>`logger.py`<br>`errors.py`<br>`http.py`<br>`filters.py`<br>`models.py`<br>`storage.py` | 跨模块共享能力：配置读取与校验、JSON Lines 日志、自定义异常与错误处理策略、HTTP 重试/限流策略、机器人账号过滤规则、数据模型定义、SQLite 日报历史 | 不包含业务规则、不感知具体数据源字段、不负责编排 |
| main.py | `main.py` | 编排入口：按顺序调用采集层→生成层→站点层→推送层，处理全局异常与工作日判断，记录执行状态 | 不实现采集/生成/推送细节 |

**关于 `shared/models.py` 与 `shared/http.py`**：书中示例的共享层只列了 config/logger/errors/storage 四个文件。本期把数据模型与 HTTP 重试策略也收回共享层，理由是：五个模块都要引用同一份数据模型定义，若放在采集层会导致生成层反向依赖采集层；重试与限流策略是 proposal 中"错误处理"这一非功能约束的统一实现，写在每个采集器里会造成三份重复代码。

## 3. 数据模型

字段只承载语义，不绑定实现（代码中用 dataclass 表达）。

### CommitRecord（代码提交记录）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| author | str | 提交者（GitHub 用户名；缺失时退化为提交邮箱） |
| message | str | 提交信息（Commit Message 首行） |
| timestamp | datetime | 提交时间（带时区） |
| repo | str | 仓库名（`owner/repo`） |
| additions | int | 新增行数 |
| deletions | int | 删除行数 |
| files_changed | int | 变更文件数 |

### TaskRecord（任务变更记录）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| assignee | str | 负责人（GitHub 用户名；未分配时退化为状态变更执行者，再退化为 Issue 创建者） |
| title | str | 任务标题（Issue 标题） |
| status_from | str | 原状态：新建 / 进行中 / 已完成 |
| status_to | str | 新状态：新建 / 进行中 / 已完成 |
| updated_at | datetime | 状态变更时间 |

### MessageRecord（协作讨论记录）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| sender | str | 发言者（GitHub 用户名） |
| content | str | 讨论内容（纯文本，报告中截断展示） |
| timestamp | datetime | 发言时间 |
| source | str | 讨论来源（如 `owner/repo #12`，替代书中的"群名称"） |

### MemberReport（成员报告）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| name | str | 成员姓名 |
| github_username | str | GitHub 用户名（成员映射键） |
| commits | list[CommitRecord] | 代码提交记录 |
| tasks | list[TaskRecord] | 任务变更记录 |
| messages | list[MessageRecord] | 相关讨论记录 |
| work_hours | WorkHoursRecord \| None | 当日工时记录（v1.1 新增；为空表示未参与统计） |

### WorkHoursRecord（工时记录，v1.1 新增）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| hours | float | 推导工时（小时，落在 0.5h 网格上） |
| session_count | int | 工作段数量（会话法切分结果） |
| commit_count | int | 参与推导的提交条数 |
| state | str | ok（有工时） / empty（无提交） / unavailable（提交数据源失败） |
| detail | str | 口径或不可用原因说明 |

### DailyReport（每日报告）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| date | date | 日报日期 |
| team_name | str | 团队名称 |
| members | list[MemberReport] | 各成员的日报段落 |
| generated_at | datetime | 生成时间 |
| markdown | str | 完整的 Markdown 格式日报 |
| html | str | 完整的 HTML 格式日报 |
| source_statuses | list[SourceStatus] | 各数据源采集状态（本期新增，用于"数据获取失败"标注与推送决策） |
| total_hours | float | 团队总工时（v1.1 新增；等于各成员工时之和） |
| member_count | int | 参与统计的成员数（v1.1 新增；用于计算人均） |

### SourceStatus（数据源状态）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| name | str | 数据源标识：github_commit / github_issue / github_discussion |
| ok | bool | 本次采集是否成功 |
| count | int | 采集到的记录条数 |
| error | str | 失败原因（成功时为空串） |

## 4. 接口契约

### 4.1 采集层

```python
collect(config: Config, start: datetime, end: datetime) -> list[CommitRecord | TaskRecord | MessageRecord]
```

- 三个采集器导出同名函数 `collect`，签名一致，参数为完整配置对象与左闭右开的采集窗口。
- 失败时抛出 `CollectorError`，由编排层捕获并写入 `SourceStatus`，采集器自身不打印业务流程决策。
- 采集器必须支持分页（GitHub 默认每页 30~100 条），并在共享层 `http.py` 中统一实现超时重试与限流等待。
- 限流预算：单次运行的"逐条提交统计"与"Issue timeline 查询"数量分别由 `max_commit_details`、`max_issue_timelines` 限制；超出上限后退化为零统计或按 `closed_at`/`created_at` 字段推断，并记录警告日志。
- 任务进展只统计**真正的 Issue**：GitHub 的 `issues` 端点会同时返回 Pull Request（带 `pull_request` 字段），采集器显式跳过它们，避免与"代码提交"板块重复计数；PR 的产出通过提交与评审评论体现。
- 去重口径：同一个 Issue 在**同一次运行**里只保留窗口内**最后一次**状态变更（例如"上午新建、下午关闭"只会输出「进行中 → 已完成」），避免同一条任务在日报里刷屏；若希望两次变更分别出现，请分两次运行。

### 4.2 生成层

```python
generate(
    date, members, commits, tasks, messages, source_statuses, team_name,
    *, timezone_name: str = "Asia/Shanghai", hours_rules: HoursRules | None = None,
) -> DailyReport
```

- 输入为原始记录列表（已跨数据源合并）与成员映射、数据源状态；输出 `DailyReport`，其中 `markdown` 与 `html` 均已填充。
- 生成层不访问网络、不读写文件、不做去重之外的业务判断。
- v1.1 起 `timezone_name` 与 `hours_rules` 为**仅关键字参数且带默认值**，旧调用无需改动（回归约束）。
- 渲染规则：成员段落固定按"代码提交→任务进展→工时统计→协作沟通"四节输出；空数据节输出"今日无记录"；`source_statuses` 中失败的数据源在对应节输出"数据获取失败（原因）"；工时不可用时输出"工时数据不可用（原因）"。
- 日报头部增加汇总行：`工时：团队合计 X.Xh · 人均 Y.Yh（按提交时间推导，非真实考勤）`，人均 = 合计 ÷ 成员数。

工时推导契约（v1.1 新增，纯计算，不访问网络）：

```python
derive(members, commits, window, timezone_name: str, rules: HoursRules) -> dict[str, WorkHoursRecord]
```

- `members` 为纳入统计的成员（含 `include_others` 追加的成员），键为成员身份标识；未匹配到任何成员的提交不参与统计。
- `rules` 由配置 `hours` 块构造（见 §6.4），默认：切分间隔 60 分钟、收尾 0.5h、网格 0.5h、单日上限 12h。
- 生成层调用时传入**无界窗口**：提交在采集层已按采集窗口裁剪，避免二次过滤造成口径漂移；`window` 参数供直接调用 `derive()` 或复用时使用。
- 算法：按自然日（`timezone_name`）分组提交 → 相邻提交间隔 **> gap_minutes** 时切分新工作段（等于阈值不切分）→ 每段时长 = 末次 − 首次 + wrap_up_hours（孤提交的段 = wrap_up_hours）→ 逐日按 daily_cap_hours 封顶 → 按 rounding_hours 网格四舍五入 → 求和。
- 状态判定：提交数据源失败 → 全员 `unavailable`；成功但该成员无提交 → `empty`（hours = 0）；否则 `ok`。

### 4.3 站点层

```python
render_site(report: DailyReport, history: list[HistoryEntry], site_config: SiteConfig) -> list[Path]
```

- 输入当日日报、历史条目（来自 SQLite）与站点配置，输出写入的文件路径列表。
- 产物：`<site_dir>/index.html`、`<site_dir>/daily-report-YYYY-MM-DD.html`、`<site_dir>/assets/style.css`、`<site_dir>/.nojekyll`。
- 索引条目按日期倒序排列；历史中缺少对应详情页文件的日期自动跳过。

### 4.4 推送层

```python
send(report: DailyReport, target: EmailTarget | LarkBotTarget) -> bool
```

- 邮件：标题含日期与团队名，正文为 `report.html`；SMTP 发送失败重试 2 次，仍失败返回 `False` 并记错误日志。
- 飞书机器人：发送 Markdown 文本消息；发送失败重试 2 次，仍失败返回 `False` 并记错误日志。
- 推送层只接受目标配置对象，不读取全局配置、不决定"是否应该推送"。

## 5. 技术选型（ADR）

### ADR-001：使用 httpx 作为 HTTP 客户端

**状态**：已采纳

**背景**：需要调用 GitHub REST API（多个端点、分页、限流），且团队后续可能复用为异步采集。

**选项**

| 选项 | 优点 | 缺点 |
| --- | --- | --- |
| requests | 社区最广泛，文档丰富 | 无原生异步，连接池与超时控制较弱 |
| httpx | 同步异步双模式，API 兼容 requests，支持 HTTP/2，超时/传输层可注入（便于测试 MockTransport） | 相对较新 |
| aiohttp | 成熟的异步库 | 仅异步，API 风格差异大 |

**决策**：使用 httpx（同步模式）。

**理由**：proposal 要求 5 人团队单次生成 < 60s，同步 + 连接复用已足够；测试可直接注入 `httpx.MockTransport` 而不触网；未来切异步不需要换库。

### ADR-002：使用 SQLite 存储日报历史

**状态**：已采纳

**背景**：静态日报站索引页需要历史日报列表，proposal 要求本地 SQLite。

**选项**

| 选项 | 优点 | 缺点 |
| --- | --- | --- |
| SQLite | 零部署零运维、Python 内置、文件级备份 | 高并发写入弱、超大数据量查询性能下降 |
| PostgreSQL | 功能完整、并发强 | 需独立部署运维，对 5 人日报场景过重 |
| JSON 文件 | 实现最简单 | 无查询能力、并发写入不安全、规模增长难管理 |

**决策**：使用 SQLite。

**理由**：proposal 明确"定时任务、不需常驻服务"，不存在并发写入；5 人团队一年约 1250 条记录；`sqlite3` 属标准库，无需额外依赖。

### ADR-003：GitHub 单数据源映射为三个采集器

**状态**：已采纳

**背景**：书中三个板块分别来自 GitHub Commit、飞书任务、飞书群消息。本期只允许使用 GitHub，必须为"任务进展""协作沟通"找到 GitHub 原生替代，同时保留书中"三个采集模块可并行"的依赖结构。

**选项**

| 选项 | 优点 | 缺点 |
| --- | --- | --- |
| 单文件 `collector/github.py` 拉全部 | 文件数少 | 单文件承担三类端点与过滤规则，任务无法并行，粒度偏粗 |
| 按数据源拆三个文件（Commit / Issue / Discussion） | 与书中 Task 3/4/5 一一对应，可并行开发与独立 Mock 测试；失败隔离边界天然清晰 | 需要在共享层抽出公共 HTTP 与映射逻辑 |
| 引入 GraphQL 一次取全 | 请求数少 | 一次性投入大，权限与查询复杂度高，超出本期范围 |

**决策**：拆为 `github_commit.py`、`github_issue.py`、`github_discussion.py`。

**理由**：与书中模块粒度与依赖图保持一致；三类数据对应三个板块，职责单一；失败隔离到单个板块，满足"单一数据源失败不阻断其他数据源"的验收标准。

### ADR-004：静态日报站 + GitHub Pages，而不是常驻 Web 应用

**状态**：已采纳

**背景**：需要让干系人方便地浏览日报。可选常驻 Web 服务（FastAPI/Flask + 鉴权）或静态站点。

**选项**

| 选项 | 优点 | 缺点 |
| --- | --- | --- |
| 常驻 Web 应用 | 可交互、可手动触发 | 与 proposal"不常驻服务""不做登录权限"冲突；需服务器与运维 |
| 静态站 + GitHub Pages | 零服务器、零密钥、零 CI；与管道架构的产物天然契合 | 只读，不能交互；`docs/` 内容公开 |
| 只输出本地 HTML | 最省事 | 干系人需要拿到文件，分享成本高 |

**决策**：生成静态站，发布路径为 GitHub Pages「Deploy from a branch → main → /docs」。

**理由**：日报是管道的**产物**而非**服务**，静态化与"定时任务、不常驻"的约束一致；不需要额外依赖与凭据。代价是页面只读、且 `docs/` 内容随之公开，因此：

1. 日报正文不含代码差异内容，只有 `+N/-N` 统计；
2. 讨论内容经过敏感词黑名单过滤；
3. 站点输出目录可配置，团队如不接受公开可改为 `output/` 仅本地预览。

### ADR-005：用 venv + pip，而不强依赖 uv

**状态**：已采纳

**背景**：书中 Task 1 使用 `uv sync`。本项目交付环境为 Windows + 已有 Python 3.12，未安装 uv。

**决策**：`pyproject.toml` 声明依赖（`httpx`、`PyYAML`、`jinja2`，测试附 `pytest`），安装方式为 `python -m venv .venv` + `pip install -e ".[dev]"`；已装 uv 的环境仍可直接 `uv sync`。

**理由**：依赖清单与书中一致，仅安装器不同；避免为教学复现额外引入工具链依赖。

### ADR-006：工时不接飞书考勤，改为从提交时间推导（v1.1）

**状态**：已采纳

**背景**：v1.1 需求要求在日报中给出每位成员的工时。书中示例通过飞书考勤 API 获取真实的签到签退数据，但本项目既有约束是"数据源只使用 GitHub"（proposal §2.2），且交付环境没有飞书应用凭据。

**选项**

| 选项 | 优点 | 缺点 |
| --- | --- | --- |
| 飞书考勤 API（照书） | 工时真实，有签到签退 | 需要飞书应用与权限；推翻"数据源只用 GitHub"的约束；离线无法测试 |
| 提交时间推导（会话法） | 零新增数据源与凭据；可离线单测；与现有采集层零耦合；可解释、可复现 | 只是近似值：开会、写文档、读代码不会被计入 |
| 人工填报（评论/提交信息里写工时） | 数据准确 | 增加成员负担，容易漏填 |

**决策**：采用**提交时间推导**，算法为会话法，切分间隔、收尾时长、四舍五入网格、单日上限全部可配。

**理由**：1）不破坏 v1.0 已确立的数据源边界与凭据模型；2）纯本地计算，不消耗 GitHub API 限流预算；3）同一组提交必然得到同一结果，便于断言与回归；4）代价是"近似而非精确"，因此 §6.4 强制标注口径，并把"不接考勤数据源、不人工填报、不做精确到分钟"明确写进 proposal 的排除项。

## 6. 非功能性约束

### 6.1 错误处理策略（优雅降级）

| 场景 | 处理方式 |
| --- | --- |
| GitHub API 超时 | 重试 3 次（间隔 5s），仍失败则标记"数据获取失败" |
| GitHub API 限流（403/429） | 读取 `X-RateLimit-Reset` 等待后重试，等待上限 300s |
| 仓库为空（HTTP 409 "Git Repository is empty"） | 视为该仓库无提交数据（计 0 条）并记录警告日志，不判定为数据源失败 |
| 单个数据源完全不可用 | 跳过该数据源，日报中标注"XX 数据源不可用"，其他数据源正常采集 |
| 所有数据源都不可用 | 记录错误日志，不生成空日报，进程返回非零退出码 |
| 邮件发送失败 | 重试 2 次，仍失败则记录日志并在执行日志中标记 |
| 飞书推送失败 | 重试 2 次，仍失败则记录日志并在执行日志中标记 |
| 配置文件非法 | 启动即失败并输出明确字段名，不进入采集流程 |

关键原则：采集层失败不阻塞生成层；生成层失败不阻塞推送层（推送层需报告失败）；任何失败都必须有日志记录。

### 6.2 安全约束

1. 密钥管理：GitHub Token、SMTP 账号密码、飞书 Webhook 全部通过环境变量注入（配置文件中写 `${ENV_NAME}` 占位符），严禁在代码或配置示例中硬编码；`.env` 必须加入 `.gitignore`。
2. 数据安全：讨论内容经敏感词黑名单（薪资、绩效、裁员等，可配置）过滤；日报正文只含增删行数统计，不含代码差异内容；日志不输出 Token、邮件正文与讨论全文。
3. 访问控制：只采集配置中明确列出的仓库；不采集配置范围之外的任何数据。
4. 噪声控制：默认排除机器人账号（`user.type == "Bot"` 或登录名以 `[bot]` 结尾），避免评审机器人与 CI 账号淹没成员讨论；可用 `sources.github.exclude_bots: false` 关闭。
5. 发布范围：静态站仅发布 `docs/` 目录；若团队不接受公开，可改为 `output/` 本地预览。

### 6.3 可运维性设计

1. 日志：采用 JSON Lines 格式（便于日志分析工具解析）；级别分为 INFO（正常流程）与 ERROR（异常）；每次执行记录开始时间、各数据源采集条数与耗时、生成与推送结果、结束时间。
2. 健康检查：`python main.py --check` 校验配置必填项与环境变量、GitHub API 连通性（含限流余量）、SMTP 登录（仅在启用邮件时）、飞书 Webhook 是否已配置。
3. 配置热更新：成员映射表与仓库列表修改后，下次执行自动生效，不需要重启服务、不需要改代码。
4. 幂等性：同一日期重复执行会覆盖该日期日报与站点页面，SQLite 按日期更新，不产生重复历史。

### 6.4 口径与诚实性（v1.1 新增）

1. **工时是推导值**：由提交时间间接推算，不等同于考勤工时；日报头部必须固定标注"按提交时间推导，非真实考勤"，禁止在任何对外呈现中省略该说明。
2. **不做考核用途**：推导值仅用于观察工作节奏；proposal 已明确排除"工时与考核挂钩"的计算。
3. **参数显式可配**：切分间隔、收尾时长、四舍五入网格、单日上限全部写在配置文件中，便于团队按实际节奏调整，而不是硬编码在代码里。
4. **本地计算**：工时推导不产生任何额外的 GitHub API 请求，不影响限流预算。
