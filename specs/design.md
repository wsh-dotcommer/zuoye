# 智能日报生成器 — 架构设计

规范版本：v2.7（与 `specs/proposal.md` v2.7 对应）

## 变更记录

| 版本 | 变更类型 | 内容 |
| --- | --- | --- |
| v1.0 | 首版 | 管道式架构、三类 GitHub 采集器、三段式日报、静态站、SQLite 历史 |
| v1.1 | 需求变更（由 proposal.md v1.1 传导） | §2 生成层新增 `hours.py`；§3 新增 `WorkHoursRecord` 并扩展 `MemberReport`/`DailyReport`；§4.2 新增 `derive()` 契约并扩展 `generate()`；§5 新增 ADR-006；§6 新增口径与诚实性约束 |
| v1.1.1 | 缺陷修复（起点为代码，逆向回溯更新本文件） | §6.2 密钥管理补全：程序自动加载 `.env`（配置同目录与当前目录），优先级「真实环境变量 > `.env`」；占位符解析为空值视同缺失，由 `--check` 报出变量名。需求边界未变，故 `proposal.md` 不升版 |
| v1.2 | 需求澄清（由 proposal.md v1.2 传导） | §2 明确推送层的签名与自检职责；§4.4 新增 `check()` 契约与签名要求；§5 新增 ADR-007；§6.1/§6.3 增加飞书通道的失败处理与自检（配置模型仅新增可选字段 `notify.lark_bot.secret`，不影响既有数据模型） |
| v1.2.1 | 实现细节变更（起点为代码，逆向回溯更新本文件） | 站点与邮件的模板、样式改用参考页的设计体系（页头品牌区、衬线标题、卡片式历史列表、数据源徽章、虚线空状态；仍为零 JS、零外部资源）；`generator/templates/` 与 `assets/style.css` 重写，并修复模板中样式被自动转义导致字体栈失效的缺陷。§2 模块职责、§3 数据模型、§4 接口契约、§4.3 产物清单与四板块文案均未变，故 `proposal.md` 与 `tasks.md` 不升版 |
| v2.0 | 需求变更（由 proposal.md v2.0 传导） | §2 生成层职责扩展为"渲染页面载荷与工作台脚本"；§3 新增页面载荷与本地草稿结构；§4.3 扩展站点层契约（`interactive`、`markdown`、`SiteConfig.workbench`、载荷转义规则）；§5 新增 ADR-008（交互放浏览器端，不加服务、不加 Actions）；§6 增加工作台的安全与可用性约束。采集层、工时推导、推送层契约不变 |
| v2.1 | 需求变更（由 proposal.md v2.1 传导） | §3 `CommitRecord` 新增 `files` 字段（变更文件名）；§4.1 明确文件名复用同一次提交详情请求、不额外占用限流预算；§4.2 新增「代码提交」条目的文件名口径（最多 10 个 + `…`，无文件名退回旧格式）。采集窗口、工时推导、站点层与推送层契约不变 |
| v2.2 | 需求变更（由 proposal.md v2.2 传导） | §3 三个记录类型补链接与上下文字段（`CommitRecord.sha/url`、`TaskRecord.number/url/labels/comment_count`、`MessageRecord.url`）；§4.1 明确这些字段都来自已在请求的同一批响应；§4.2 新增内联链接、任务行括号补充与单人团队合并三项渲染口径。模板新增 `inline_links` 过滤器，站点层与推送层接口不变 |
| v2.3 | 需求变更（由 proposal.md v2.3 传导） | ①新增飞书群消息采集器与 `FeishuClient`（§2/§3/§4.1）；②`reports` 表新增结构化统计列并做幂等迁移（§3/§6.3）；③§4.2 新增「对比上期」「近 N 期」两行与趋势序列口径；④§4.3 新增索引页内联 SVG 趋势区块；⑤新增 ADR-009 与 §6.6 隐私约束。推送层契约不变 |
| v2.3.1 | 实现细节变更（起点为代码，逆向回溯更新本文件） | §4.2 补日报标题口径：由 `智能日报 · 日期` 改为 `<团队名> 智能日报 · 日期`（姓名取配置的 `team.name`，不写死）。邮件主题与飞书卡片标题不受影响，需求边界未变，故 `proposal.md` 与 `tasks.md` 不升版 |
| v2.4 | 需求变更（由 proposal.md v2.4 传导） | ①新增飞书任务采集器 `collector/feishu_task.py` 与三态映射（§2/§3/§4.1）；②新增 `FeishuTaskRecord`、`DataSourceRef` 与 `DailyReport.feishu_tasks/attribution`（§3）；③§4.2 新增「数据来源」标注口径、飞书任务子小节口径、标题分级与空板块合并规则；④§4.3 索引页接收 `attribution`、趋势门槛 2 → 3；⑤新增 ADR-010 与 §6.8 溯源约束。存储层、推送层契约与配置文件格式之外的行为均不变 |
| v2.4.1 | 实现细节变更（起点为代码，逆向回溯更新本文件） | §4.4 补邮件主题口径：新增配置 `notify.email.subject_prefix`，非空时主题由 `[团队名] 日期 智能日报` 改为 `<前缀> <团队名> <日期> 智能日报`（例：`研一 王帅豪 2026-10-13 智能日报`，前缀内多余空白自动归一），留空时行为与 v1.0 完全一致。展示文案调整、需求边界未变，故 `proposal.md` 与 `tasks.md` 不升版 |
| v2.5 | 缺陷修复（起点为代码，逆向回溯更新本文件） | 飞书任务读不到数据：飞书任务接口区分身份，应用身份（`tenant_access_token`）读「我负责的」任务时「我」指应用自己，因此永远是空。新增 `shared/feishu_oauth.py`（授权链接、授权码换令牌、refresh_token 续期、本地令牌文件）与一次性脚本 `authorize-feishu.py`，采集器在有用户令牌时改用 `user_access_token` 并同时查询 v1「我负责的」列表（§4.1）；`FeishuClient` 增加 `as_user` 维度的认证（§2）。需求边界未变，故 `proposal.md` 与 `tasks.md` 不升版 |
| v2.5.1 | 缺陷修复（起点为代码，逆向回溯更新本文件） | 授权卡在"浏览器回调到本机端口"这一环：`authorize-feishu.py` 新增 `--manual`（不启动本地服务器，把地址栏整条链接或裸授权码粘回终端，由 `shared/feishu_oauth.parse_callback_input()` 解析）、等待期每 10 秒心跳提示、失败时用 `hint_for_authorize_error()` 把错误翻译成"下一步做什么"，并把令牌文件路径打印为绝对路径。默认模式行为不变，故 `proposal.md` 与 `tasks.md` 不升版 |
| v2.5.2 | 需求澄清（起点为代码，逆向回溯更新本文件） | 飞书任务小节从"全量快照"收紧为"当天仍有意义"：新增 `FeishuTaskRecord.completed_at`，采集层在映射后隐藏"状态=已完成且完成时间早于采集窗口起点"的记录（窗口起点即日报目标日 00:00，补跑按那天算；`start` 为空或任务缺完成时间时不过滤），并记 `feishu_tasks_filtered` 日志；小节为空时文案改为「今日无飞书任务」。展示口径调整，故 `proposal.md` 与 `tasks.md` 不升版 |
| v2.6 | 缺陷修复（起点为代码，逆向回溯更新本文件） | 邮件在 PC 与手机渲染不一致、页头「日」图标消失：根因是邮件正文直接复用站点页面，依赖 9KB `<style>`、103 处 `var(--…)` 与 flex，而 QQ 邮箱 PC 端会丢弃依赖 CSS 变量的声明（白字落在透明背景上）。新增邮件专用模板 `generator/templates/email.html.j2` 与 `template.render_email_html(view)`（表格布局 + 全内联字面量样式，不含 `<style>`/class/`var()`/flex/grid/clamp），`DailyReport` 增加 `email_html`，推送层优先使用它（为空回退站点版）；`main.py` 另存 `output/daily-report-<date>.email.html` 便于排查；`inline_links` 过滤器支持传入内联链接颜色。站点页面与飞书卡片渲染不变，故 `proposal.md` 与 `tasks.md` 不升版 |
| v2.7 | 需求变更（由 proposal.md v2.7 传导） | 工时口径从"提交时间"扩到"活动时间"：`derive()` 新增仅关键字参数 `tasks` / `messages`，三类活动归一成一条活动流后仍走会话法；`WorkHoursRecord` 增加 `task_count` / `comment_count`（`commit_count` 语义不变）与 `activity_count`，`detail` 改为"提交 x · 任务 y · 评论 z，N 个工作段"（只列非零）；`WORK_HOURS_NOTE` 改为"按提交/任务/评论时间推导，非真实考勤"；`formatter._derive_work_hours()` 按 `SourceStatus` 过滤失败源，并把"提交源失败即全员不可用"放宽为"三个活动源全部失败才不可用"（§4.2/§6.4）。`tasks.md` 新增 Task 22 |

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

数据流：`main.py` 按窗口调用采集器（GitHub 三个 + 可选的飞书群、飞书任务）→ 归一为记录列表 → 生成层按成员聚合、渲染 Markdown/HTML/站点 → 存储层落库 → 推送层按配置发送。任一层失败只影响自身分支，不阻断整条管道。

注：飞书任务与其它四个源不同——它没有"时间窗"概念，取的是**此刻状态**，因此 `collect()` 的窗口参数只为满足统一签名，不参与过滤（见 §4.1）。

## 2. 模块职责

| 模块 | 文件 | 负责 | 不负责 |
| --- | --- | --- | --- |
| collector/ | `github_commit.py`<br>`github_issue.py`<br>`github_discussion.py`<br>`feishu_message.py`<br>`feishu_task.py` | 从 GitHub REST API 获取原始数据：提交记录、Issue 状态变更、PR/Issue 讨论；可选地从飞书群消息只读汇总条数与发言人数（v2.3）；可选地读取飞书工作台任务的状态快照（v2.4）；做字段标准化与配置级过滤 | 不做日报排版、不做成员聚合决策、不做推送；飞书群采集器不保留消息正文，飞书任务采集器不保留任务描述，两者都不对飞书做任何写操作 |
| generator/ | `formatter.py`<br>`hours.py`<br>`template.py`<br>`site.py` | 按成员聚合原始记录、编排日报板块、从提交时间推导工时（会话法）、生成 Markdown 与 HTML、渲染静态日报站（索引页+详情页）、把日报正文序列化为页面内联载荷并内联工作台脚本（`templates/workbench.js`） | 不做数据采集、不调用外部 API、不做推送、不提供任何服务端接口 |
| notifier/ | `email.py`<br>`lark_bot.py` | 将日报推送给目标：SMTP 邮件发送、飞书群机器人消息推送（含可选签名校验与连通性自检） | 不做数据处理、不做日报生成、不做数据采集 |
| shared/ | `config.py`<br>`logger.py`<br>`errors.py`<br>`http.py`<br>`filters.py`<br>`models.py`<br>`storage.py` | 跨模块共享能力：配置读取与校验（含 v2.4 的 `report.attribution` 与 `sources.feishu.tasks`）、JSON Lines 日志、自定义异常与错误处理策略、HTTP 重试/限流策略（含 v2.3 的 `FeishuClient` 与 `tenant_access_token` 认证，群消息与任务共用同一客户端）、机器人账号过滤规则、数据模型定义、SQLite 日报历史（含 v2.3 结构化统计列与幂等迁移） | 不包含业务规则、不感知具体数据源字段、不负责编排 |
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
| files | tuple[str, ...] | 变更文件名（v2.1 新增；来自提交详情端点的 `files` 数组，GitHub 单次最多返回 300 个；未取详情统计的提交为空元组） |
| sha | str | 提交 SHA（v2.2 新增；渲染时截取前 7 位作为短号） |
| url | str | 提交页面链接（v2.2 新增；缺失时条目退化为只显示短号） |

### TaskRecord（任务变更记录）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| assignee | str | 负责人（GitHub 用户名；未分配时退化为状态变更执行者，再退化为 Issue 创建者） |
| title | str | 任务标题（Issue 标题） |
| status_from | str | 原状态：新建 / 进行中 / 已完成 |
| status_to | str | 新状态：新建 / 进行中 / 已完成 |
| updated_at | datetime | 状态变更时间 |
| number | int | Issue 编号（v2.2 新增） |
| url | str | Issue 页面链接（v2.2 新增） |
| labels | tuple[str, ...] | Issue 标签（v2.2 新增；对象数组与字符串数组两种 API 形态都归一为名称元组） |
| comment_count | int | Issue 评论总数（v2.2 新增） |

### MessageRecord（协作讨论记录）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| sender | str | 发言者（GitHub 用户名） |
| content | str | 讨论内容（纯文本，报告中截断展示） |
| timestamp | datetime | 发言时间 |
| source | str | 讨论来源（如 `owner/repo #12`，替代书中的"群名称"） |
| url | str | 评论页面链接（v2.2 新增；缺失时来源保持 `[source]` 原样） |

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
| feishu_tasks | list[FeishuTaskRecord] | 本次运行读到的飞书任务快照（v2.4 新增；未启用时为空列表） |
| attribution | str | 对外产物末尾的「数据来源」标注整行文本（v2.4 新增；未启用或没有数据源时为空串） |

### SourceStatus（数据源状态）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| name | str | 数据源标识：github_commit / github_issue / github_discussion / feishu_message（v2.3）/ feishu_task（v2.4） |
| ok | bool | 本次采集是否成功 |
| count | int | 采集到的记录条数；飞书群源为"消息总条数"（v2.3），飞书任务源为"任务条数"（v2.4） |
| error | str | 失败原因（成功时为空串） |

### ChatSummaryRecord（飞书群汇总，v2.3 新增）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| chat_name | str | 群名（取自配置 `sources.feishu.chats[].name`） |
| message_count | int | 窗口内真人消息条数 |
| speaker_count | int | 窗口内去重后的发言人数 |

> 该模型**没有**消息内容字段：正文在采集器里就地丢弃（见 §6.6）。

### FeishuTaskRecord（飞书任务快照，v2.4 新增）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| guid | str | 飞书任务唯一标识 |
| summary | str | 任务标题 |
| status | str | 三态之一：已完成 / 进行中 / 未开始（`STATUS_DONE` / `STATUS_IN_PROGRESS` / `STATUS_NOT_STARTED`） |
| due | date \| None | 截止日期；飞书未设置时为空 |
| updated_at | datetime \| None | 飞书侧最后更新时间 |
| url | str | 任务链接；飞书未返回时为空串 |

> 与 `TaskRecord` 的区别：`TaskRecord` 是"状态流转"（`status_from → status_to`），本模型是"此刻状态"。该模型**没有**任务描述字段：描述在采集器里就地丢弃（见 §6.6）。
>
> `STATUS_NOT_STARTED`（"未开始"）只属于本模型；GitHub Issue 流转仍沿用 `STATUS_NEW`（"新建"），两者不互相替代。

### DataSourceRef（数据来源标注项，v2.4 新增）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| label | str | 数据源类别，如 `GitHub 仓库`、`飞书群`、`飞书任务` |
| full_name | str | 具体对象，如 `wsh-dotcommer/zuoye`、群名；缺省时标注里只出现 label |

> 由编排层按"本次实际参与采集的数据源"组装后传给生成层；生成层只负责拼接成整行标注（见 §4.2），不感知数据源细节。

### ReportStats（日报结构化统计，v2.3 新增）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| date | date | 日报日期 |
| commit_count / task_count / message_count / chat_message_count | int | 各数据源当期的记录条数 |
| total_hours | float | 当期团队合计工时 |

> 与 `reports.sqlite3` 的统计列一一对应（见 §6.3），供「对比上期」与「近 N 期趋势」使用，避免反向解析 Markdown。

### WorkbenchPayload（页面内联载荷，v2.0 新增）

渲染时序列化进页面 `<script id="workbench-data" type="application/json">` 的只读数据，供工作台脚本在浏览器本地使用，不产生任何网络请求。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| reports | list[dict] | 可载入的日报列表；索引页为全部历史期数，详情页只有当期一条 |
| reports[].date | str | 日报日期（`YYYY-MM-DD`） |
| reports[].markdown | str | 该期日报的 Markdown 原文 |

序列化规则：`<`、`>`、`&` 一律转成 JSON 的 `\uXXXX` 形式，保证正文里的 `</script>` 等序列无法提前闭合脚本标签。

### DraftRecord（本地草稿，v2.0 新增，仅存在于浏览器）

保存在使用者浏览器 `localStorage`（键 `daily-report-workbench:history:v1`）中的手写日报记录，**不进入 SQLite、不进入仓库、不参与推送**。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | str | 记录标识（`日期-时间戳`） |
| date | str | 日报日期（同日期重复生成时覆盖旧记录） |
| savedAt | int | 保存时间（毫秒时间戳） |
| report | str | 手写日报正文（Markdown 格式） |

约束：最多保留 50 条；列表按 `savedAt` 倒序展示；详情页到索引页的跳转中转使用键 `daily-report-workbench:pending:v1`（单条 `{date, report}`），工作台读取后立即删除。

## 4. 接口契约

### 4.1 采集层

```python
collect(config: Config, start: datetime, end: datetime) -> list[CommitRecord | TaskRecord | MessageRecord]
```

- 三个采集器导出同名函数 `collect`，签名一致，参数为完整配置对象与左闭右开的采集窗口。
- 失败时抛出 `CollectorError`，由编排层捕获并写入 `SourceStatus`，采集器自身不打印业务流程决策。
- 采集器必须支持分页（GitHub 默认每页 30~100 条），并在共享层 `http.py` 中统一实现超时重试与限流等待。
- 限流预算：单次运行的"逐条提交统计"与"Issue timeline 查询"数量分别由 `max_commit_details`、`max_issue_timelines` 限制；超出上限后退化为零统计或按 `closed_at`/`created_at` 字段推断，并记录警告日志。
- 变更文件名（v2.1）：与"增删行数、变更文件数"来自**同一次**提交详情请求，采集器只做字段映射，不额外发起请求、不额外占用限流预算；超出 `max_commit_details` 上限或详情请求失败的提交，`files` 为空元组，提交记录本身仍然保留。
- 链接与上下文字段（v2.2）：`sha` / `html_url` / `labels` / `comments` 全部取自采集器**已经在请求**的同一批响应（提交列表、Issue 列表、评论列表），不新增任何 HTTP 请求，限流预算不变。
- 飞书群消息（v2.3）：新增 `collector/feishu_message.py`，契约 `collect(config, start, end) -> list[ChatSummaryRecord]`。用 `FeishuClient` 换 `tenant_access_token`（单次运行一次），逐群调用 `GET /open-apis/im/v1/messages`（`container_id_type=chat` + `container_id` + 秒级 `start_time/end_time` + `page_token` 翻页），按左闭右开窗口二次裁剪 `create_time`（毫秒时间戳）；跳过 `sender_type=app` 与 `msg_type=system`，只累计条数与去重发言人数。`sources.feishu.enabled` 为假时**直接返回空列表且不发任何请求**，编排层也不把它放进采集计划。
- 飞书任务（v2.4）：新增 `collector/feishu_task.py`，契约 `collect(config, start=None, end=None) -> list[FeishuTaskRecord]`。复用 `feishu_message.build_client`（同一个 `FeishuClient`、同一份 `tenant_access_token`、同一套超时重试），翻页调用 `GET /open-apis/task/v2/tasks`（`page_size` + `page_token`）；`sources.feishu.tasks.scope = tasklist` 时改调 `GET /open-apis/task/v2/tasklists/<guid>/tasks`，逐个清单串行拉取。窗口参数只用于满足统一签名，**不参与过滤**——任务取的是此刻状态。`tasks.enabled` 为假时**直接返回空列表且不发任何请求**。条数上限 `tasks.max_tasks`（默认 200），超出截断并记 `feishu_tasks_truncated`。
- 飞书任务三态映射（v2.4）：`completed_at` 非空且不为 `0` → 已完成；未完成且 `start.timestamp` 在**未来** → 未开始；其余未完成 → 进行中。飞书未返回 `start` 字段时退化为"未完成即进行中"，该退化路径在本节记录为已知口径（真实字段以权限到位后的只读探测结果为准）。
- 飞书任务只读边界（v2.4）：只映射 `guid/summary/completed_at/start/due/updated_at` 六个字段，`description` 就地丢弃；不做任何写操作（不新建、不修改、不完成、不删除任务）。
- 权限错误翻译（v2.4）：飞书返回 `99991672`（缺少 action scope）时，采集器把原始报文替换为可执行提示——"请在开发者后台为该应用添加 `task:task:read` 与 `task:tasklist:read` 权限并重新发布版本"——避免把一整段英文报文塞进日报（见 §6.1）。
- 用户身份（v2.5）：飞书任务接口区分身份，`tenant_access_token` 下的"我负责的"指的是**应用自己**，因此应用身份读不到个人工作台任务。采集器在 `sources.feishu.tasks.use_user_token` 为真**且本地已有授权令牌**时，改用 `user_access_token` 调 `GET /open-apis/task/v2/tasks` 与 `GET /open-apis/task/v1/tasks?type=my_tasks`，按 `guid`/`id` 去重合并（两个任务空间的任务可能只出现在一边）；没有令牌时自动退回应用身份，行为与 v2.4 一致。v1 的任务对象没有开始时间字段，因此 v1 来源的任务只会出现「已完成 / 进行中」两态。
- 时间戳兼容（v2.5）：飞书 v2 的时间字段是秒级、v1 是毫秒级，`due` 对象的键名也分别是 `timestamp` 与 `time`；`_to_moment()` 按数值位数（≥10^12 视为毫秒）与两种键名统一解析。
- 展示口径（v2.5.2）：`_hide_old_completed()` 在映射后隐藏"状态 = 已完成 且 `completed_at` 早于采集窗口起点"的记录——留未完成的全部（进行中 / 未开始 / 逾期未完成）与**基准之后完成**的。基准取 `collect()` 的 `start`（普通运行 = 日报目标日 00:00，补跑历史日期 = 那天 00:00）；`start` 为空或已完成任务缺 `completed_at` 时不过滤（fail-open）。过滤在采集层完成，因此 `SourceStatus.count`（数据源徽章）与小节条数一致；隐藏条数记入 `feishu_tasks_filtered` 日志。小节为空时的文案是「今日无飞书任务」，同时覆盖"本来就没任务"与"更早完成的都被隐藏了"。
- 任务进展只统计**真正的 Issue**：GitHub 的 `issues` 端点会同时返回 Pull Request（带 `pull_request` 字段），采集器显式跳过它们，避免与"代码提交"板块重复计数；PR 的产出通过提交与评审评论体现。
- 去重口径：同一个 Issue 在**同一次运行**里只保留窗口内**最后一次**状态变更（例如"上午新建、下午关闭"只会输出「进行中 → 已完成」），避免同一条任务在日报里刷屏；若希望两次变更分别出现，请分两次运行。

### 4.2 生成层

```python
generate(
    date, members, commits, tasks, messages, source_statuses, team_name,
    *, timezone_name: str = "Asia/Shanghai", hours_rules: HoursRules | None = None,
    recent: Sequence[ReportStats] = (), chat_summaries: Sequence[ChatSummaryRecord] = (),   # v2.3
    feishu_tasks: Sequence[FeishuTaskRecord] = (), source_refs: Sequence[DataSourceRef] = (),
    attribution_scope: str = "",                                                            # v2.4
) -> DailyReport
```

- 输入为原始记录列表（已跨数据源合并）与成员映射、数据源状态；输出 `DailyReport`，其中 `markdown` 与 `html` 均已填充。
- 生成层不访问网络、不读写文件、不做去重之外的业务判断。
- v1.1 起 `timezone_name` 与 `hours_rules` 为**仅关键字参数且带默认值**，旧调用无需改动（回归约束）。
- 渲染规则：成员段落固定按"代码提交→任务进展→工时统计→协作沟通"四节输出；空数据节输出"今日无记录"；`source_statuses` 中失败的数据源在对应节输出"数据获取失败（原因）"；工时不可用时输出"工时数据不可用（原因）"。
- 日报标题（v2.3.1）：`build_view()["title"]` 为 `<团队名> 智能日报 · <日期>`（例：`王帅豪 智能日报 · 2026-10-12`），团队名取自配置 `team.name`。该值是**共用**的——邮件正文 `<h1>` 与 `<title>`、站点详情页 `<h1>` 与 `<title>`、`output/*.md` 首行、页面内联工作台载荷里的 Markdown 全部同源，因此改一处四处生效。邮件主题（`[团队名] 日期 智能日报`）与飞书卡片标题（`团队名 · 日期 智能日报`）各由推送层单独拼装，不在本口径内。
- 邮件主题的例外（v2.4.1）：上一条说的"邮件主题不在本口径内"仍然成立——`notify.email.subject_prefix` 非空时主题改用 `<前缀> <团队名> <日期> 智能日报`（例 `研一 王帅豪 2026-10-13 智能日报`），与正文标题、飞书卡片标题互不影响；留空时维持 `[团队名] 日期 智能日报`。
- 标题分级（v2.4）：`build_view()` 新增 `heading`，值为 `<团队名> 智能日报`（不带日期），供正文 `<h1>` 与 Markdown 的 `# ` 首行使用；`title` 仍是带日期的完整标题，只用于页面 `<title>` 标签与页头品牌区。日期改由头部信息行承载（`- 日期：YYYY-MM-DD`），窄屏不再把日期断成两行。
- 头部信息行（v2.4）：HTML 侧拆成两段——第一段 `日期：… · 团队：… · 生成时间：…`，第二段 `工时：团队合计 …h · 人均 …h（口径）`；Markdown 侧保持"每项一条 `- ` 列表项"的既有形态，只新增 `- 日期：` 一条。
- 空板块合并（v2.4）：成员段落生成后做一次后处理——`MERGEABLE_SECTION_KEYS`（commits/tasks/messages）里状态为 `empty` 的板块 ≥ 2 个时，合并为一条 `今日无记录：板块 A、板块 B`，留在第一个空板块的位置，其余空板块移除；工时统计与飞书任务带各自口径，不参与合并。板块视图新增 `key` 字段供该规则判断，合并项带 `merged=True`，HTML 用 `.empty-line`（一行文字）而不是虚线方框渲染。
- 「数据来源」标注（v2.4）：`build_attribution(generated_at, source_refs, scope, timezone_name)` 拼出整行——`数据来源：<各源全称，顿号分隔> ｜ 采集时间：YYYY-MM-DD HH:MM（时区）｜ 授权范围：<scope>`；`source_refs` 为空或 `attribution_scope` 未传时返回空串，调用方据此不渲染，旧调用的产物逐字不变。时区用 `ATTRIBUTION_TIMEZONE_LABELS` 映射（`Asia/Shanghai` → `北京时间`），未命中时直接写时区名。该行共用一份文本：Markdown 由 `_finish_markdown()` 追加在末尾，HTML 由模板渲染为页脚前的 `<p class="attribution">`，飞书卡片跟随 Markdown。
- 飞书任务子小节（v2.4）：`_feishu_task_section()` 生成一个 `sub=True` 的板块，挂在「任务进展」之后、工时统计之前，且**只渲染一次**（挂在 `members[0]` 上，避免多成员时重复）。小节标题为 `任务进展 · 飞书任务`；`feishu_task` 不在 `source_statuses` 里时返回 `None`，连标题都不出现（未启用时产物与 v2.3 逐字一致）。首行 `- 截至 YYYY-MM-DD HH:MM · 共 N 条：进行中 x · 未开始 y · 已完成 z`（只列非零状态）；随后逐条 `- <标记> 状态 · 标题（截止 YYYY-MM-DD）`，标记为 ● 进行中 / ○ 未开始 / ✓ 已完成；排序 `进行中 → 未开始 → 已完成`，同组按截止日期升序（无截止排最后），最多 20 条（`FEISHU_TASK_LIMIT`），超出追加 `- …（其余 N 条见飞书任务）`，计数仍报全量。目标日期 ≠ 生成当天时标题追加「（补跑快照）」；源失败时输出 `飞书任务数据获取失败（原因）`；任务为空时输出 `飞书工作台暂无任务`。
- 提交行两行布局（v2.4）：板块视图新增 `entries`（`[{main, meta}]`）与 `lines` 并存——`lines` 是 Markdown/飞书的单行文本（形态不变），`entries` 供 HTML 渲染为"主行 `repo message` + 元信息行 `短 SHA 链接 · +A/-D，N 个文件：…`"，解决一条提交在窄屏折成三行的问题。HTML 模板优先用 `entries`，缺失时回退 `lines`（任务/沟通/工时板块即走回退分支）。
- 「代码提交」条目格式（v2.1）：`` - `repo` message（+A/-D，N 个文件：f1、f2、…） ``；文件名最多列 10 个（常量 `COMMIT_FILE_LIMIT`，超出时在第 10 个后追加 `、…`，数量已在前文给出、不重复计数）；`files` 为空时退回 `（+A/-D，N 个文件）`，不出现空冒号。文件名不加反引号，`&`/`<`/`>` 交由既有 Markdown / HTML 转义处理；Markdown、站点详情页与邮件正文共用这一份文本，因此三端自动一致。
- 条目链接（v2.2）：Markdown 版输出 `[文字](链接)`（提交行短 SHA 7 位、任务行 `#编号`、协作沟通行来源标识）；站点详情页与邮件正文的 HTML 侧由 `generator/template.py` 的 `inline_links` 过滤器把同一串文本转成 `<a href target="_blank" rel="noopener">`——先按片段转义文本与锚点文字、URL 作为属性值转义，只认 `http(s)` 链接，不做完整 Markdown 渲染。缺链接时提交行只输出短号、任务行只输出 `#编号`；SHA 与编号都缺时整段省略，不出现空壳标记。
- 任务行括号补充（v2.2）：依次为 `标签：a、b`、`指派：X`、`N 条评论`，三段用 ` · ` 连接，没有的片段整体不出现；`指派` 与本段成员的 `github_username` 一致时省略（日报按人聚合，写自己名字是噪音）。
- 单人团队合并（v2.2）：`len(members) == 1` 时头部输出 `- 团队：<团队名>（@<username>）` 并省略成员标题（Markdown 的 `## 姓名（username）` 与 HTML 的成员面板头）；成员数为 2 及以上时行为与 v2.1 完全一致。
- 头部补充行（v2.3）：在「工时」行之后按顺序追加三行可选项，空的不出现——①`- 飞书群：群名 N 条 · M 人发言`（多群用 `；` 连接）；②`- 对比上期（YYYY-MM-DD）：提交 ±N · 任务 ±N · 沟通 ±N · 工时 ±N.Nh`，基数取 `recent[-1]`（最近一期已保存日报），其日期不早于当日或无历史时整行不出现；③`- 近 N 期：提交 ▁▂▃█（合计条数）· 工时 ▁▂▃█（合计小时）`，序列 = `recent` 末尾 6 期 + 当日本期，不足 2 期不出现。三行在 Markdown 与 HTML 中共用 `build_view()["extra_lines"]`，因此邮件正文与飞书卡片自动一致。
- 迷你趋势字符（v2.3）：8 档块字符 `▁▂▃▄▅▆▇█` 按 `value / max(values)` 归一化取档；最大值 ≤ 0 时全部取最低档（不虚高）；差值文本用 `±0` 表示零、负值带 `-`、工时带 `h` 后缀并沿用 `_format_hours` 的去尾零规则。
- 日报头部增加汇总行：`工时：团队合计 X.Xh · 人均 Y.Yh（按提交/任务/评论时间推导，非真实考勤）`，人均 = 合计 ÷ 成员数。

工时推导契约（v1.1 新增，v2.7 口径扩展；纯计算，不访问网络）：

```python
derive(members, commits, window, timezone_name: str, rules: HoursRules,
       *, tasks: Sequence[TaskRecord] = (), messages: Sequence[MessageRecord] = ()) -> dict[str, WorkHoursRecord]
```

- `members` 为纳入统计的成员（含 `include_others` 追加的成员），键为成员身份标识；未匹配到任何成员的活动不参与统计。
- 活动三类（v2.7）：提交按 `author`、Issue 状态变更按 `assignee`（时刻取 timeline 里**那次变更**的时间，不是 Issue 的 `updated_at`）、评论按 `sender`；三类合成一条活动流后统一走会话法。`tasks` / `messages` 是**仅关键字参数且默认空**，因此 v1.1 以来的旧调用行为完全不变。
- `rules` 由配置 `hours` 块构造（见 §6.4），默认：切分间隔 60 分钟、收尾 0.5h、网格 0.5h、单日上限 12h。
- 生成层调用时传入**无界窗口**：活动在采集层已按采集窗口裁剪，避免二次过滤造成口径漂移；`window` 参数供直接调用 `derive()` 或复用时使用。
- 算法：按自然日（`timezone_name`）分组活动 → 相邻活动间隔 **> gap_minutes** 时切分新工作段（等于阈值不切分）→ 每段时长 = 末次 − 首次 + wrap_up_hours（孤立活动的段 = wrap_up_hours）→ 逐日按 daily_cap_hours 封顶 → 按 rounding_hours 网格四舍五入 → 求和。
- 状态判定（v2.7）：**三个活动源全部失败** → 全员 `unavailable`；有成功源但该成员无活动 → `empty`（hours = 0）；否则 `ok`。失败的数据源其记录不参与推导（`formatter._derive_work_hours` 里按 `SourceStatus` 过滤后再调用）。
- 计数与文案（v2.7）：`WorkHoursRecord` 带 `commit_count` / `task_count` / `comment_count`，`detail` 拼成"提交 x · 任务 y · 评论 z，N 个工作段"，**只列非零类别**（避免"任务 0"这种噪音）；`activity_count` 为三者之和。

### 4.3 站点层

```python
render_site(report: DailyReport, history: list[HistoryEntry], site_config: SiteConfig) -> list[Path]
render_report_html(view, *, back_link=False, markdown=None, interactive=False) -> str   # v2.0 扩展
render_index_html(entries, *, site_title, team_name, generated_at, interactive=True, trend=None, attribution="") -> str   # v2.0/v2.3/v2.4 扩展
render_workbench_js() -> str   # v2.0 新增
render_workbench_data(view_or_entries, markdown=None) -> str   # v2.0 新增
```

- 输入当日日报、历史条目（来自 SQLite）与站点配置，输出写入的文件路径列表。
- 产物：`<site_dir>/index.html`、`<site_dir>/daily-report-YYYY-MM-DD.html`、`<site_dir>/assets/style.css`、`<site_dir>/.nojekyll`。
- 索引条目按日期倒序排列；历史中缺少对应详情页文件的日期自动跳过。
- 工作台（v2.0）：`interactive=True` 时，页面在末尾内联工作台脚本与 JSON 载荷；脚本与载荷都不新增产物文件，站点仍是"四个文件 + 无后端"。
- 邮件纯净性（v2.0）：邮件正文走 `render_report_html` 的默认 `interactive=False`，因此不含脚本、不含复制/载入按钮；`render_index_html` 的 `interactive` 默认 `True`，只有站点索引页会渲染工作台。
- 载荷范围（v2.0）：索引页内联的期数等于索引条目数（受 `main.py` 的 `HISTORY_LIMIT` 约束），因此"从自动日报载入"下拉不会出现没有内容的日期。
- 关闭开关（v2.0）：`SiteConfig.workbench=False`（来自配置 `report.workbench`）时，模板不渲染工作台区块与脚本，页面回到 v1.x 的纯只读形态。
- 趋势区块（v2.3）：`site.build_trend(history)` 从历史条目的结构化统计列取最近 7 期，在 Python 里算好 SVG 柱子的坐标（`x/y/width/height` 与日期、数值文本）后交给模板；不足 3 期（v2.4 由 2 期调高，与 `formatter.TREND_MIN_POINTS` 同步）或全为 0 时返回 `None`，区块与 `<svg>` 都不渲染。柱子只由 `<rect>` 与 `<text>` 组成，**不引入任何脚本或图表库**，页面仍是零 JS（既有工作台载荷除外）。
- 数据来源标注（v2.4）：`render_site()` 把 `build_view(report)["attribution"]` 透传给 `render_index_html(attribution=...)`，索引页在存档列表之后、页脚之前渲染同一个 `<p class="attribution">`；详情页与邮件 HTML 由 `report.html.j2` 自己从 `view.attribution` 取。四处文案完全同源，改配置即四处同步变化。

### 4.4 推送层

```python
send(report: DailyReport, target: EmailTarget | LarkBotTarget) -> bool
check(target: LarkBotTarget) -> tuple[bool, str]      # v1.2
```

- 邮件：正文为邮件专用 HTML（见下条）；SMTP 发送失败重试 2 次，仍失败返回 `False` 并记错误日志。
- 邮件正文渲染（v2.6）：HTML 部分取 `report.email_html`（由 `template.render_email_html(view)` 产出——表格布局 + 全内联字面量样式，**不含** `<style>`、`class`、`var()`、flex/grid/clamp；页头色块同时写 `bgcolor` 属性兜底），为空时回退 `report.html`；纯文本部分仍是 `report.markdown`。邮件与站点共用同一份 `view`，因此两端**文字内容永远一致**，差异只在排版层（ADR-012）。
- 邮件主题（v2.4.1）：`notify.email.subject_prefix` 非空时为 `<前缀> <团队名> <日期> 智能日报`（例 `研一 王帅豪 2026-10-13 智能日报`，团队名取配置 `team.name`，前缀内多余空白会被归一），留空时为 `[<团队名>] <日期> 智能日报`（v1.0 以来的格式，向后兼容）。主题由 `notifier/email.py` 的 `build_subject()` 单独拼装，与正文标题（§4.2）、飞书卡片标题互不影响。
- 飞书机器人：发送交互式卡片（`lark_md` 渲染 Markdown），超长内容截断到 4000 字符；发送失败重试 2 次，仍失败返回 `False` 并记错误日志。
- 截断保留标注（v2.4）：截断前先把末尾的「数据来源」标注摘出来（`_split_attribution`），按 `4000 − len(标注) − 1` 的预算截正文，再把标注原样拼回末尾——标注是合规要求，不能因为正文过长就被砍掉。
- 飞书签名（v1.2）：`LarkBotTarget.secret` 非空时，载荷附带 `timestamp`（秒级）与 `sign`，`sign = Base64(HMAC-SHA256(key=secret, msg="{timestamp}\n{secret}"))`；`secret` 为空时载荷与 v1.1 完全一致，保证向后兼容。
- 飞书自检（v1.2）：`check()` 发送一条 `msg_type=text` 的纯文本消息，返回 `(是否成功, 人类可读说明)`；不重试、不生成日报，供 `main.py --test-lark` 使用。
- 错误定位（v1.2）：飞书返回 19021（签名不匹配）/19024（关键词不匹配）/19001（参数错误）时，错误日志附带一句可执行的排查提示。
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

### ADR-007：飞书推送用"群自定义机器人 Webhook"，而不是企业自建应用（v1.2）

**状态**：已采纳

**背景**：proposal 2.1 要求"把日报推送到团队群"。飞书提供两条路径：群里的**自定义机器人 Webhook**（粘贴一个地址即可发消息），与企业**自建应用**（需在开放平台建应用、申请 `im:message` 等权限、走 `tenant_access_token` 鉴权、还要处理可见范围与管理员审批）。

**选项**

| 选项 | 优点 | 缺点 |
| --- | --- | --- |
| 群自定义机器人 Webhook | 零申请、零审批、零 token 管理；一个 URL 即可推消息 | 只能推给配置的那一个群；只能写不能读；安全设置需与实现匹配（签名/关键词/白名单） |
| 企业自建应用 | 可推任意会话、可 @ 指定人、可读消息 | 需管理员审批权限；要额外管理 `app_id`/`app_secret` 与 token 生命周期 |

**决策**：选**群自定义机器人 Webhook**，并同时实现飞书的「签名校验」算法与 `--test-lark` 自检命令。

**理由**：本期需求是"每天往团队群推一条日报"，属于只写单向通知；用自建应用会为一个发消息的需求引入权限审批与 token 管理，与 proposal 2.2"不做常驻服务、不做权限体系"的取舍冲突。

**代价**：① 换群要重新配 Webhook；② 不能读飞书消息，所以飞书无法反过来当数据源（与 proposal 2.2 一致）；③ 安全设置若选「签名校验」，载荷必须带 `timestamp`/`sign`，否则飞书返回 19021——已由 §4.4 的签名契约覆盖；④ 机器人被移出群或停用后推送会静默失败，因此提供 `--test-lark` 让接入方在正式推送前发现通道已断。

### ADR-008：工作台交互放在浏览器端，而不是加服务或 CI（v2.0）

**状态**：已采纳

**背景**：v2.0 要求在页面上提供表单、复制与本地历史。可选路径有三条：加一个常驻 Web 服务提供生成接口；用 GitHub Actions 在网页上触发云端重新生成；把交互全部放在浏览器本地。

**选项**

| 选项 | 优点 | 缺点 |
| --- | --- | --- |
| 常驻 Web 服务 | 表单可以真正调用采集与生成 | 与 proposal §2.2"不做常驻 Web 服务"冲突；需要服务器、端口、鉴权与运维 |
| 网页触发 GitHub Actions | 能复用采集逻辑 | 需要在网页里放触发凭据（等于公开密钥）或额外网关；引入 CI 与密钥，破坏"零密钥发布" |
| 浏览器端工作台 | 零后端、零密钥、零新依赖；与静态站产物天然契合 | 表单产出的是"手写日报"，不能直接调用 GitHub 采集；草稿只在本机 |

**决策**：交互全部放在浏览器端，用渲染时内联的 JSON 载荷驱动，页面不发起任何网络请求。

**理由**：1）`docs/` 的发布路径仍是"GitHub Pages + main/docs"，不引入服务、端口与密钥，交接成本最低；2）自动日报仍由定时任务生成，工作台只负责"人工整理与补充"，两者职责不混；3）代价是"手写内容不能自动合并进自动日报、草稿不跨设备"，因此把这两点写进 proposal §2.2 的排除项，并在页面上明示"内容不会上传"。

### ADR-009：趋势图用内联 SVG，而不是引入图表库或 Canvas（v2.3）

**状态**：已采纳

**背景**：v2.3 要求在索引页展示"近 7 期提交数与工时趋势"。可选路径有三条：引 ECharts/Chart.js 之类的图表库；用 Canvas 手写绘制；直接在模板里手写内联 SVG。

**选项**

| 选项 | 优点 | 缺点 |
| --- | --- | --- |
| 图表库（ECharts / Chart.js） | 交互能力最强，代码最少 | 违反 §6.5"不引入第三方脚本与外部资源"；`docs/` 会从四个文件膨胀；新增 npm/构建链 |
| Canvas 手写 | 无外部依赖 | 需要 JS：不仅违反"零 JS"叙事，还会在禁用脚本时整块消失，与渐进增强的既有约定冲突 |
| 内联 SVG（几何在 Python 算好） | 零 JS、零外部资源、无 DOM 依赖；禁用脚本也能看；可无障碍标注 | 表达能力有限（只适合柱状/折线这类简单图），改样式要改模板 |

**决策**：用内联 SVG，柱子的坐标、日期与数值文本全部在 `generator/site.py` 里算好，模板只负责输出 `<rect>` 与 `<text>`。

**理由**：1）守住"页面不发请求、零外部资源"的既有红线（§6.5、ADR-004），`docs/` 仍是四个文件；2）禁用 JavaScript 时趋势图照常显示，比 Canvas 方案更符合渐进增强；3）缺点是图表能力有限，因此把展示范围限定为"提交数 + 工时"两张柱状图，不承诺下钻与交互。

### ADR-010：数据来源标注放在生成层统一渲染，而不是推送到各端分别拼装（v2.4）

**背景**：proposal v2.4 要求"所有对外发送的结构化数据末尾"追加带三要素的数据来源标注。本项目对外有四张面孔：邮件正文（纯文本 + HTML）、飞书群卡片、站点详情页、站点索引页。

**选项对比**：

| 方案 | 优点 | 代价 |
| --- | --- | --- |
| 在推送层各写一份（邮件一份、飞书一份、站点一份） | 各端可自由排版 | 四份文案迟早漂移；新增对外通道时要记得再补一份；测试要覆盖四遍 |
| 在生成层拼成一行文本，塞进 `view["attribution"]` | 一处定义、四处消费；合规测试只需断言"这一行在四端都出现"；新增通道自动继承 | 各端只能整行复用，不能各自改写措辞（本项目可接受） |
| 每期日报把来源存进 SQLite 再读出来 | 历史可追溯 | 与"每期数据源可能不同"耦合，且历史行没有该列时要迁移；收益不足 |

**决策**：在生成层由 `build_attribution()` 拼成单行文本，写入 `DailyReport.attribution` 与 `view["attribution"]`；Markdown 渲染器负责追加到正文末尾，两个 HTML 模板各自渲染为 `<p class="attribution">`，飞书卡片直接跟随 Markdown。

**理由**：1）三要素是合规要求，唯一实现才不会有遗漏与漂移；2）数据源全称来自编排层（只有它知道本次真正启用了哪些源），因此用 `DataSourceRef` 显式传递，生成层不反向依赖配置；3）`source_refs` 默认空 → 旧调用与旧测试的产物逐字不变，升级零风险。

### ADR-011：飞书任务只做"生成时快照"，不做定时刷新与常驻同步（v2.4）

**背景**：proposal v2.4 曾要求"任务状态定时刷新（间隔不超过 15 分钟）"。实现前评估后发现本项目没有常驻进程（ADR-004 明确排除），且 `GITHUB_TOKEN` 未配置时 GitHub 走匿名配额（60 次/小时），一次完整采集约消耗 20 次请求。

**选项对比**：

| 方案 | 优点 | 代价 |
| --- | --- | --- |
| 计划任务每 15 分钟重跑整条流水线 | 无需新增机制（`--dry-run` 已具备） | 每小时 4 次 × 约 20 次请求 = 80 次/小时，**超过匿名配额 60 次/小时**；还会反复重写当日产物 |
| 计划任务每 15 分钟只同步任务并重渲染当日页面 | 时效性最好（≤15 分钟） | 需要给 `reports` 表加 `view_json` 列、新增 `--sync-tasks` 命令与定向重渲染路径，并把当日页面变成"活页"；与"日报是快照"的既有语义冲突 |
| 生成日报时取一次快照（本决策） | 零新增机制、零新增存储列、配额不变；口径诚实（标题里写明快照时间） | 时效性等于"日报重新生成的频率"；想看最新状态要重跑一次 |

**决策**：采用第三种。任务状态取"生成日报那一刻"的快照，小标题里显式标注快照时间；补跑历史日期时额外标注「补跑快照」。proposal §2.2 明确把"定时刷新与常驻同步"列为排除项。

**理由**：1）在不新增常驻进程与不增加限流预算的前提下，快照方案的信息是**诚实**的——读者看到的每个状态都对应一个明确的时间戳，而"15 分钟的活页"反而会让人误以为页面数字是当天累计；2）收益与成本不成比例：日报本身是每日一次的产物，"分钟级刷新"对日报读者没有实际增量；3）若日后确实需要，`--sync-tasks` 是一条独立的演进路径，不阻塞本期交付。

### ADR-012：邮件与网页分流——邮件走专用内联样式模板（v2.6）

**背景**：邮件正文原本直接复用站点详情页的 HTML（`render_report_html`），即"一个完整网页 + 9KB `<style>` 块"。实测在 QQ 邮箱 PC 端与手机端渲染差异很大：胶囊标签退化成一排黑字、强调色丢失，页头那个「日」方块（白字 + `var(--accent)` 背景）**整字消失**。

**选项对比**：

| 方案 | 优点 | 代价 |
| --- | --- | --- |
| 继续复用站点 HTML | 一处渲染、内容天然一致 | 邮件客户端支持度参差；依赖 `var()` 的声明被丢就出现隐形文字；修一个客户端可能弄坏另一个 |
| 给 CSS 变量加字面量回退（`var(--x, #hex)`） | 改动最小 | 只对"支持 var() 但丢了 `:root`"的客户端有效；对完全不支持 `var()` 的引擎无效；flex 布局差异仍在 |
| 邮件专用模板：表格布局 + 全内联字面量样式 | 不依赖任何"看客户端脸色"的能力；页头用 `bgcolor` 属性兜底，即使 CSS 背景被丢弃白字也有底色 | 多一份模板；邮件 HTML 体积略增；站点与邮件的视觉需要人工保持同源 |

**决策**：新增 `generator/templates/email.html.j2` + `template.render_email_html(view)`，邮件不再带 `<style>`、`class`、`var()`、flex/grid/clamp，颜色与间距一律内联字面量；关键色块（页头「日」）同时写 `bgcolor` 属性与 `background-color` 内联样式，双保险。站点页面继续使用带 CSS 变量的富样式（浏览器 100% 支持，不值得为邮件降级）。

**理由**：1）Markdown、站点、邮件共用同一份 `view`，内容仍然同源，分歧只发生在"怎么把这些内容画出来"这一层，这正是应该分开的地方；2）邮件与网页是两种交付媒介，强行共用一套 CSS 只会让两边都不舒服；3）通用 CSS 全部内联后，邮件在 QQ 邮箱 PC/手机、Gmail、Outlook 的表现趋于一致，也顺带免疫了未来任何"某个客户端擅自改样式"的问题。

**代价与约束**：邮件模板不参与站点样式演进，日后加板块时要**同步改两份模板**（`report.html.j2` 与 `email.html.j2`），单元测试对邮件 HTML 的"禁用构造"做了硬断言，防止有人把站点写法又抄回去。

### ADR-013：工时的输入从"提交时间"扩到"活动时间"（v2.7）

**背景**：v1.1 起工时只由提交时间推导。实际使用中暴露出明显失真：某天写了两份文档、改了 Issue 状态、在评审里回了三条评论，但只要当天没有 commit，日报就显示 `0h（今日无记录）`——数字与"今天干了多少活"脱节，团队成员也会因此觉得这个板块没意义。

**选项对比**：

| 方案 | 优点 | 代价 |
| --- | --- | --- |
| 维持"只算提交" | 口径简单、数字稳定、历史可比 | 与真实节奏严重脱节；非编码类工作日恒为 0 |
| 接飞书考勤/打卡 | 最接近真实工时 | 需要考勤权限与审批；推翻"数据源只用 GitHub"的既有约束；离线无法测试 |
| 手填工时 | 最准 | 与"自动生成"的目标相悖；增加成员负担 |
| 活动时间（提交 + 任务状态变更 + 评论） | 全部来自已有数据源，零新增请求；能反映"今天确实在干活" | 数字普涨，历史出现跳变；三种痕迹被等价对待（一次评论与一次提交权重相同） |

**决策**：把三类时间戳合成一条活动流，交给同一套会话法（间隔 > 60 分钟切段、每段 +0.5h 收尾、0.5h 网格、单日 12h 上限）。标注文案同步改为"按提交/任务/评论时间推导，非真实考勤"；板块行只列非零类别。降级规则放宽：三个活动源全部失败才判"不可用"，单个源失败不再作废整块工时（失败源由头部徽章标注）。

**理由**：1）三类痕迹都来自已经采集的数据，新增零成本、零权限；2）会话法的"间隔切段"天然适配稀疏的活动点，不需要引入新的度量模型；3）口径变更**不回溯历史**——已生成的日报保持不变，趋势与「对比上期」出现的一次性跳变是可解释的，好过悄悄改写历史数字。

**代价与约束**：工时数字普遍变大，活跃日更容易触到 12h 上限；一次评论与一次提交在算法里权重相同（都是"一个时间点"），这是有意的简化——本项目的工时只用于观察节奏，不作考核（§6.4）。

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
| 飞书推送失败 | 重试 2 次，仍失败则记录日志并在执行日志中标记（含签名不匹配 19021、关键词不匹配 19024 的排查提示）；推送失败不影响日报生成与站点渲染 |
| 飞书 Webhook 未配置 | `--test-lark` 立即提示缺失的变量名并返回非零退出码，不发起网络请求；正常流水线只记 `push_skipped`，不中断整条管道 |
| 飞书任务接口未授权（99991672） | 标记该源失败，error 文案替换为"补 `task:task:read` / `task:tasklist:read` 权限并重新发布"的可执行提示；不影响其它源与推送（v2.4） |
| 飞书任务清单为空 | 视为该源**成功但无数据**，日报输出"飞书工作台暂无任务"，不判定为失败（v2.4） |
| 配置文件非法 | 启动即失败并输出明确字段名，不进入采集流程 |

关键原则：采集层失败不阻塞生成层；生成层失败不阻塞推送层（推送层需报告失败）；任何失败都必须有日志记录。

### 6.2 安全约束

1. 密钥管理：GitHub Token、SMTP 账号密码、飞书 Webhook 全部通过环境变量注入（配置文件中写 `${ENV_NAME}` 占位符），严禁在代码或配置示例中硬编码；`.env` 必须加入 `.gitignore`。程序启动时自动加载配置文件同目录与当前工作目录下的 `.env`（共享层 `config.py` 实现，无第三方依赖），优先级为「真实环境变量 > `.env`」；占位符解析为空字符串时同样视为缺失，由 `--check` 明确报出变量名。
2. 数据安全：讨论内容经敏感词黑名单（薪资、绩效、裁员等，可配置）过滤；日报正文只含增删行数统计，不含代码差异内容；日志不输出 Token、邮件正文与讨论全文。
3. 访问控制：只采集配置中明确列出的仓库；不采集配置范围之外的任何数据。
4. 噪声控制：默认排除机器人账号（`user.type == "Bot"` 或登录名以 `[bot]` 结尾），避免评审机器人与 CI 账号淹没成员讨论；可用 `sources.github.exclude_bots: false` 关闭。
5. 发布范围：静态站仅发布 `docs/` 目录；若团队不接受公开，可改为 `output/` 本地预览。

### 6.3 可运维性设计

1. 日志：采用 JSON Lines 格式（便于日志分析工具解析）；级别分为 INFO（正常流程）与 ERROR（异常）；每次执行记录开始时间、各数据源采集条数与耗时、生成与推送结果、结束时间。
2. 健康检查：`python main.py --check` 校验配置必填项与环境变量、GitHub API 连通性（含限流余量）、SMTP 登录（仅在启用邮件时）、飞书 Webhook 是否已配置（只做配置检查，不发消息）。
3. 通道自检（v1.2）：`python main.py --test-lark` 只向飞书群发一条纯文本自检消息，成功返回 0、失败返回非 0，并打印人类可读的排查说明；它不受 `notify.lark_bot.enabled` 开关限制，因此可以在正式开启推送前先验证通道。
4. 配置热更新：成员映射表与仓库列表修改后，下次执行自动生效，不需要重启服务、不需要改代码。
5. 幂等性：同一日期重复执行会覆盖该日期日报与站点页面，SQLite 按日期更新，不产生重复历史。

### 6.4 口径与诚实性（v1.1 新增）

1. **工时是推导值**：由 GitHub 活动时间（提交 / Issue 状态变更 / 评论）间接推算，不等同于考勤工时；日报头部必须固定标注"按提交/任务/评论时间推导，非真实考勤"，禁止在任何对外呈现中省略该说明。文案常量是 `WORK_HOURS_NOTE`，邮件、站点、飞书三端共用。
2. **不做考核用途**：推导值仅用于观察工作节奏；proposal 已明确排除"工时与考核挂钩"的计算。
3. **参数显式可配**：切分间隔、收尾时长、四舍五入网格、单日上限全部写在配置文件中，便于团队按实际节奏调整，而不是硬编码在代码里。
4. **本地计算**：工时推导不产生任何额外的 GitHub API 请求，不影响限流预算。

### 6.5 工作台安全与可用性（v2.0 新增）

1. **不新增攻击面**：页面不发请求、不写仓库、不引入第三方脚本与外部资源（无 CDN、无字体、无图片），`docs/` 仍只由四个文件组成。
2. **载荷转义**：内联 JSON 载荷中的 `<`、`>`、`&` 一律转义为 `\uXXXX`，日报正文里的 `</script>` 等序列无法逃出脚本标签（对应单测：注入 `</script><script>alert(1)</script>` 后页面不含该原始序列）。
3. **一律纯文本渲染**：工作台与本地草稿列表只用 `textContent` 与 `document.createElement` 构造 DOM，禁止把用户输入或日报正文交给 `innerHTML`。
4. **草稿不外传**：手写草稿只写浏览器 `localStorage`，不进入 SQLite、不进入仓库、不参与飞书与邮件推送；页面上固定展示"内容不会上传"的提示。
5. **渐进增强**：工作台区块默认带 `hidden`，脚本就绪后才显示；脚本被禁用时页面退回 v1.x 的只读形态。`localStorage` 不可用（隐私模式）时，工作台仍可生成与复制，但改成提示"草稿只在本次会话内有效"。
6. **复制降级**：优先使用 Clipboard API；不可用时退回 `document.execCommand("copy")`；仍失败则选中内容并提示手动复制，不抛未捕获异常。
7. **可关闭**：配置 `report.workbench: false` 可重新生成不含任何脚本的纯只读站点，作为团队不接受页面交互时的逃生开关。

### 6.6 飞书群消息的隐私边界（v2.3 新增）

1. **只取计数**：数据源只产出"条数 + 去重发言人数"（`ChatSummaryRecord` 没有内容字段），正文在采集器里就地丢弃。
2. **不落盘**：消息正文不写模型、不写 SQLite、不写 Markdown/HTML、不写 JSON Lines 日志（连失败留痕也只记群名与错误原因）。
3. **不改推送通道**：群消息读取走只读的企业自建应用（`tenant_access_token`），推送仍走群自定义机器人 Webhook；两者的凭据分别放在 `FEISHU_APP_ID/FEISHU_APP_SECRET` 与 `LARK_BOT_WEBHOOK/LARK_BOT_SECRET`，互不复用。
4. **默认关闭**：`sources.feishu.enabled` 默认 `false`；未启用时采集计划里没有这一项，日报与站点与 v2.2 完全一致。
5. **公开页面约束**：`docs/` 发布后是公开页面，因此飞书相关的展示只允许出现群名与计数，任何情况下都不允许把消息正文写进页面。
6. **用户令牌的存放（v2.5）**：`user_access_token` / `refresh_token` 只落在本地文件 `data/feishu-user-token.json`（`data/` 已在 `.gitignore` 中），不进版本库、不写日志、不写日报产物；`authorize-feishu.py` 的回调处理器也不把回调参数打进终端。

### 6.7 存储迁移（v2.3 新增）

1. `reports` 表的建表语句已包含 `commit_count` / `task_count` / `message_count` / `chat_message_count` / `total_hours` 五个统计列。
2. 老库（v2.3 之前创建）在 `Storage` 实例化时用 `PRAGMA table_info` 检测缺列并 `ALTER TABLE ... ADD COLUMN` 补齐，**幂等**且不重建表、不动旧数据。
3. 补齐后的旧行这些列为 `NULL`，语义是"无可比数据"：对比与趋势都会跳过它们，而不是当成 0 参与计算。

### 6.8 数据溯源约束（v2.4 新增）

1. **对外产物必带标注**：邮件正文（纯文本 + HTML）、飞书群卡片、站点详情页、站点索引页四处都必须出现「数据来源」标注；新增对外通道时必须沿用同一份文本（`view["attribution"]` / `report.attribution`），不允许各端自行改写。
2. **三要素不可缺**：标注固定包含"数据源全称、采集时间、授权使用范围"，顺序不变；采集时间用生成时的本地时间并附时区名（如 `北京时间`），不使用 UTC 以免读者换算。
3. **只列真实来源**：数据源全称来自本次**实际参与采集**的数据源（含采集失败但已进入计划的源）；未启用的源不出现，避免标注与内容不符。
4. **授权范围可配**：第三要素由 `report.attribution.scope` 决定（默认"仅限团队内部日报展示"），团队按实际约定修改；`report.attribution.enabled: false` 可整体关闭（用于确实不需要溯源的场景）。
5. **截断不丢标注**：飞书卡片按 4000 字符截断时，标注行必须完整保留在末尾（见 §4.4）。
6. **飞书任务最小必要字段**：只取 `guid/summary/completed_at/start/due/updated_at`，任务描述与评论不采集、不落盘、不进日志——与 §6.6 的群消息边界同一条原则：只取展示所必需的信息，其余一律不取。
