# 智能日报生成器 — 任务清单

## 元信息

- 关联规范：`specs/proposal.md`、`specs/design.md`
- 任务总数：23（v1.1 新增 Task 11，v1.2 新增 Task 12，v2.0 新增 Task 13/14/15，v2.1 新增 Task 16，v2.2 新增 Task 17，v2.3 新增 Task 18/19，v2.4 新增 Task 20/21，v2.7 新增 Task 22，v2.8 新增 Task 23）
- 预计总执行时间：4 到 6h（包含测试）
- 执行策略：按依赖关系顺序执行，独立任务可并行执行
- 相对书中的扩展点：书中采集层为 GitHub + 飞书任务 + 飞书消息，本期改为三个 GitHub 采集器（Task 3/4/5）；书中无静态站，本期把站点渲染并入生成层（Task 6）并在 Task 1 落地 `docs/` 与 Pages 基础文件。

## 变更记录

| 版本 | 变更类型 | 内容 |
| --- | --- | --- |
| v1.0 | 首版 | Task 1–10（见下方） |
| v1.1 | 需求变更 | 新增 Task 11「实现工时推导模块」；修改 Task 6 验收标准（新增工时板块与布局顺序）；执行顺序插入"阶段 4：Task 11 → 阶段 5：Task 6" |
| v1.1.1 | 缺陷修复 | 密钥注入失效：程序未加载 `.env`（只读系统环境变量），占位符空值未视为缺失；修复后 Task 9 补充两条验收标准 |
| v1.2 | 需求澄清 | 新增 Task 12「接入飞书群机器人」；修改 Task 8 验收标准（新增签名校验与自检）；执行顺序追加"阶段 9：Task 12" |
| v2.0 | 需求变更 | 新增 Task 13「实现工作台前端资源」、Task 14「页面接入工作台与载荷」、Task 15「工作台测试与文档回归」；Task 6 的产物清单不变（仍是四个文件）；执行顺序追加"阶段 10–12" |
| v2.1 | 需求变更 | 新增 Task 16「日报列出提交变更文件名」；修改 Task 3 的验收标准（`CommitRecord` 字段数 7 → 8）；执行顺序追加"阶段 13：Task 16" |
| v2.2 | 需求变更 | 新增 Task 17「条目链接与任务上下文」；修改 Task 3/4/5/6 的验收标准（链接与上下文字段、HTML 锚点渲染、单人团队合并）；执行顺序追加"阶段 14：Task 17" |
| v2.3 | 需求变更 | 新增 Task 18「近 N 期趋势与对比」、Task 19「飞书群消息只读数据源」；修改 Task 2 的验收标准（结构化统计列与幂等迁移）；执行顺序追加"阶段 15–16" |
| v2.4 | 需求变更 | 新增 Task 20「数据来源标注与日报可读性改进」、Task 21「飞书任务状态同步」；修改 Task 6 的验收标准（标题分级、头部拆行、空板块合并、提交行两行制、趋势门槛 3 期、四处来源标注）；执行顺序追加"阶段 17–18" |
| v2.7 | 需求变更 | 新增 Task 22「工时口径扩展到活动时间」；修改 Task 11 的验收标准（三类活动、计数与 detail 文案、降级规则）与 Task 6 的验收标准（工时行与口径说明）；执行顺序追加"阶段 19" |
| v2.8 | 需求变更 | 新增 Task 23「团队管理摘要与在线日报入口」；修改 Task 6 的验收标准（邮件、站点与飞书三端展示管理摘要）和 Task 9（`report.public_base_url`）；执行顺序追加"阶段 20" |

---

## Task 1: 创建项目结构和基础配置

描述：初始化项目目录结构，创建 `pyproject.toml`，声明核心依赖，创建配置模板与运行说明。

输入：`specs/design.md` §2（模块职责定义）

输出：项目根目录结构 + `pyproject.toml` + `config.yaml.example` + `.env.example` + `.gitignore` + `README.md`

依赖：无

验收标准：

- [ ] 目录结构符合 design.md §2 的模块划分（`collector/`、`generator/`、`notifier/`、`shared/`、`tests/`、`docs/`）
- [ ] `pyproject.toml` 包含 `httpx`、`PyYAML`、`jinja2` 三个运行依赖，以及 `pytest` 开发依赖
- [ ] `python -m venv .venv` + `pip install -e ".[dev]"` 能成功安装全部依赖
- [ ] `config.yaml.example` 包含 `team`、`repos`、`members` 映射表、`sources`、`report`、`notify` 六个配置块
- [ ] `docs/.nojekyll` 存在，README 写明 GitHub Pages 的开启步骤（main 分支 /docs）

---

## Task 2: 实现共享基础层

描述：实现配置读取校验、JSON Lines 日志、自定义异常、HTTP 重试与限流策略、数据模型、SQLite 存储六个共享模块。

输入：`config.yaml.example`（配置格式）、`specs/design.md` §3（数据模型）、§6（非功能约束）

输出：`shared/config.py`、`shared/logger.py`、`shared/errors.py`、`shared/http.py`、`shared/models.py`、`shared/storage.py` + `tests/test_shared.py`

依赖：Task 1

验收标准：

- [ ] `config.py` 能读取 `config.yaml` 并返回强类型配置对象，解析 `${ENV_NAME}` 占位符
- [ ] `config.py` 在配置缺少必填字段时抛出带字段名的明确错误信息
- [ ] `logger.py` 输出 JSON Lines 格式日志，且不写入密钥与讨论全文
- [ ] `errors.py` 定义 `CollectorError`、`GeneratorError`、`NotifierError`、`ConfigError` 四个自定义异常
- [ ] `http.py` 支持超时重试 3 次（间隔可配）、403/429 限流等待 reset（等待上限可配），并可通过注入 transport 在测试中离线运行
- [ ] `storage.py` 能创建 SQLite，按日期幂等写入并查询日报记录
- [ ] `storage.py` 在 v2.3 起同时落库结构化统计列，并对 v2.3 之前的老库做幂等列迁移（旧行为 `NULL`，见 design.md §6.7）
- [ ] `http.py` 在 v2.3 起提供 `FeishuClient`（`tenant_access_token` 认证 + 同样的重试策略），业务返回码 `code != 0` 视为失败
- [ ] 全部模块包含对应单元测试，测试通过

---

## Task 3: 实现 GitHub 提交采集模块

描述：调用 GitHub REST API 获取指定仓库在采集窗口内的 Commit 记录（含变更统计），返回 `CommitRecord` 列表。

输入：`specs/design.md` §3（CommitRecord 数据模型）、§4.1（采集层接口契约）

输出：`collector/github_commit.py` + `tests/test_github_commit.py`

依赖：Task 2

验收标准：

- [ ] `collect()` 函数签名符合 design.md §4.1 的接口定义
- [ ] 返回的每个 `CommitRecord` 包含全部 8 个字段且类型正确（v2.1 起新增 `files`，即变更文件名元组）
- [ ] 机器人账号的提交默认被排除（`exclude_bots: true`）
- [ ] 支持分页查询（GitHub API 默认每页 30 条，本实现按 100 条分页直到取完）
- [ ] 逐条提交的变更统计通过详情端点获取，并受 `max_commit_details` 上限保护
- [ ] 空仓库（HTTP 409）视为 0 条提交并记录警告日志，不标记数据源失败
- [ ] API 超时重试 3 次（间隔 5s），若仍失败则抛出 `CollectorError`（由编排层标记该数据源失败）
- [ ] 使用 Mock 数据的单元测试全部通过

---

## Task 4: 实现 GitHub Issue 采集模块

描述：调用 GitHub REST API 获取当日发生状态变更的 Issue 列表，通过 timeline 事件推导 `status_from` 与 `status_to`，返回 `TaskRecord` 列表。

输入：`specs/design.md` §3（TaskRecord 数据模型）、§4.1（采集层接口契约）

输出：`collector/github_issue.py` + `tests/test_github_issue.py`

依赖：Task 2

验收标准：

- [ ] `collect()` 函数签名符合 design.md §4.1 的接口定义
- [ ] 返回的每个 `TaskRecord` 包含全部 5 个字段且类型正确
- [ ] 关闭事件推导为「进行中 → 已完成」，重新打开事件推导为「已完成 → 进行中」，窗口内新建且未关闭推导为「新建 → 进行中」
- [ ] 未分配负责人的 Issue 退化为「状态变更执行者 → Issue 创建者」，不因缺少 assignee 而丢记录
- [ ] 采集窗口外的状态变更与仅评论变更的 Issue 不会出现在结果中
- [ ] Pull Request（issues 接口中带 `pull_request` 字段的条目）被显式排除，不与"代码提交"重复计数
- [ ] 同一个 Issue 在单次运行中只保留窗口内最后一次状态变更
- [ ] timeline 不可用时退化为按 `closed_at` / `created_at` 推断并记录警告日志，不静默跳过
- [ ] timeline 查询数量受 `max_issue_timelines` 上限保护，超出后改走字段推断
- [ ] 使用 Mock 数据的单元测试全部通过

---

## Task 5: 实现 GitHub 讨论采集模块

描述：调用 GitHub REST API 获取 Issue 评论与 PR 评审评论，按关键词白名单与敏感词黑名单过滤，返回 `MessageRecord` 列表。

输入：`specs/design.md` §3（MessageRecord 数据模型）、§4.1（采集层接口契约）

输出：`collector/github_discussion.py` + `tests/test_github_discussion.py`

依赖：Task 2

验收标准：

- [ ] `collect()` 函数签名符合 design.md §4.1 的接口定义
- [ ] 返回的每个 `MessageRecord` 包含全部 4 个字段且类型正确，`source` 记录仓库与 PR/Issue 编号
- [ ] 关键词过滤正确：只返回包含配置关键词的讨论（关键词列表为空时返回全部）
- [ ] 敏感关键词（薪资、绩效、裁员等）被正确过滤，不出现在结果中
- [ ] 机器人账号（`[bot]` / `user.type == "Bot"`）的评论默认被排除，可通过 `exclude_bots: false` 关闭
- [ ] 采集窗口外的评论被剔除
- [ ] 使用 Mock 数据的单元测试全部通过

---

## Task 6: 实现日报生成与静态站渲染模块

描述：接收各成员的采集数据，按"代码提交→任务进展→工时统计→协作沟通"组织日报内容，输出 Markdown 与 HTML，并渲染静态日报站的索引页与详情页。

输入：`specs/design.md` §3（MemberReport、DailyReport、SourceStatus 数据模型）、§4.2（生成层接口契约）、§4.3（站点层接口契约）

输出：`generator/formatter.py`、`generator/template.py`、`generator/site.py` + `tests/test_generator.py`、`tests/test_site.py`

依赖：Task 2

验收标准：

- [ ] `generate()` 函数签名符合 design.md §4.2 的接口定义
- [ ] `render_site()` 函数签名符合 design.md §4.3 的接口定义
- [ ] 输出的 `DailyReport.markdown` 包含"代码提交""任务进展""协作沟通"三个板块标题
- [ ] 输出的 `DailyReport.html` 可被浏览器正确渲染，与 Markdown 内容一致
- [ ] 若某成员当日无任何记录，对应板块显示"今日无记录"
- [ ] 若某数据源采集失败，对应板块显示"数据获取失败"并附原因
- [ ] 站点产出 `index.html`、`daily-report-<date>.html`、`assets/style.css`、`.nojekyll`，索引页包含当日日报链接
- [ ] 使用 Mock 数据的单元测试全部通过

v1.1 新增验收标准：

- [ ] 日报（Markdown 与 HTML）必须包含每位成员的工时统计
- [ ] 工时统计板块位于"任务进展"之后、"协作沟通"之前
- [ ] 日报头部显示团队总工时与人均工时，并带口径说明"按提交/任务/评论时间推导，非真实考勤"（v2.7 更新）
- [ ] 成员当日无提交时显示 `0h（今日无记录）`；提交数据源失败时显示 `工时数据不可用（原因）`
- [ ] `generate()` 的新增参数为仅关键字且带默认值，旧调用无需修改即可通过（回归约束）

---

## Task 7: 实现邮件推送模块

描述：将 HTML 格式日报通过 SMTP 发送给指定收件人。

输入：`specs/design.md` §4.4（推送层接口契约）

输出：`notifier/email.py` + `tests/test_email.py`

依赖：Task 6

验收标准：

- [ ] `send()` 函数签名符合 design.md §4.4 的接口定义
- [ ] 邮件主题包含日期和团队名称
- [ ] 邮件正文为 HTML 格式的日报内容
- [ ] 发送失败时重试 2 次，仍失败则返回 `False` 并记录错误日志
- [ ] 使用 Mock SMTP 的单元测试通过

---

## Task 8: 实现飞书推送模块

描述：将 Markdown 格式日报通过飞书群机器人 Webhook 发送到指定群。

输入：`specs/design.md` §4.4（推送层接口契约）

输出：`notifier/lark_bot.py` + `tests/test_lark_bot.py`

依赖：Task 6

验收标准：

- [ ] `send()` 函数签名符合 design.md §4.4 的接口定义
- [ ] 发送的消息为 Markdown 格式，且超长内容被截断为合法长度
- [ ] 发送失败时重试 2 次，仍失败则返回 `False` 并记录错误日志
- [ ] 使用 Mock Webhook 的单元测试通过
- [ ] `LarkBotTarget` 支持可选 `secret`；配置后载荷附带符合飞书官方算法的 `timestamp` 与 `sign`，未配置时载荷与 v1.1 一致（v1.2）

---

## Task 9: 实现主编排入口

描述：创建 `main.py` 作为系统入口，按顺序编排"采集→聚合→生成→站点渲染→推送"的完整流程。

输入：所有模块的接口

输出：`main.py`

依赖：Task 3、Task 4、Task 5、Task 6、Task 7、Task 8

验收标准：

- [ ] `python main.py --config config.yaml` 执行完整的日报生成流程
- [ ] `python main.py --check` 验证配置必填项、环境变量、GitHub 连通性与推送配置
- [ ] `python main.py --dry-run` 执行采集、生成与站点渲染，但不推送
- [ ] 支持 `--date YYYY-MM-DD`（补跑历史某日）与 `--since/--until` 覆盖采集窗口
- [ ] 若单个数据源失败，不影响其他数据源的采集，日报中标注该板块"数据获取失败"
- [ ] 若所有数据源失败，不生成空日报，记录错误日志并返回非零退出码
- [ ] 非工作日（周末及 `holidays` 列表）自动跳过生成
- [ ] 执行日志包含：开始时间、各数据源采集条数、生成与推送结果、结束时间

v1.1.1 补充验收标准（缺陷修复）：

- [ ] 启动时自动加载 `.env`（配置文件同目录与当前工作目录），密钥解析优先级为「真实环境变量 > `.env`」
- [ ] 占位符在 `.env` 中为空值或未设置时，`--check` 必须**点名报出变量名**（如 `SMTP_PASSWORD`）
- [ ] `.env` 文件带 BOM（记事本保存）时仍能正确解析第一行的键

---

## Task 10: 集成测试

描述：编写端到端集成测试，验证完整流程在正常、降级、空数据、全部失败四种场景下的行为。

输入：`main.py` + 所有模块

输出：`tests/test_integration.py`

依赖：Task 9

验收标准：

- [ ] 正常场景：三个数据源可用，日报 Markdown/HTML 与站点页面全部生成，推送被调用且返回成功
- [ ] 降级场景：某个数据源超时，日报中对应板块标注"数据获取失败"，其他板块正常
- [ ] 空数据场景：某成员当日无任何记录，日报中显示"今日无记录"
- [ ] 全部失败场景：所有数据源不可用，不生成日报文件，返回非零退出码并记录错误日志
- [ ] `--dry-run` 场景不触发任何推送
- [ ] 索引页包含当日日报链接且详情页文件存在
- [ ] 全部测试在 Mock 环境下执行，耗时少于 60s，且不访问真实网络

---

## Task 11: 实现工时推导模块（新增 v1.1）

描述：按会话法从成员当日的提交时间推导工时，产出 `WorkHoursRecord`，供生成层渲染"工时统计"板块。

输入：`specs/design.md` §3（WorkHoursRecord 数据模型）、§4.2（工时推导契约）、§6.4（口径与诚实性约束）

输出：`generator/hours.py` + `tests/test_hours.py`

依赖：Task 2

验收标准：

- [ ] `derive()` 函数签名符合 design.md §4.2 的工时推导契约
- [ ] 会话切分正确：相邻提交间隔 59 分钟归入同一段、60 分钟（等于阈值）不切分、61 分钟切分为新段
- [ ] 只有一条提交的工作段按收尾时长计（默认 0.5h）
- [ ] 每段时长 = 末次 − 首次 + 收尾时长，结果按配置网格（默认 0.5h）四舍五入
- [ ] 单人单日封顶（默认 12h），超出部分被截断
- [ ] 跨天窗口按自然日分别封顶再求和；提交时间按 `team.timezone` 归属到正确自然日
- [ ] 提交数据源失败 → 全员 `unavailable`；成功但成员无提交 → `empty`（hours = 0）
- [ ] 成员归属复用现有映射，`include_others` 追加的成员同样参与统计
- [ ] 纯本地计算：不产生任何 GitHub API 请求
- [ ] 基于 Mock 数据的单元测试全部通过

---

## Task 12: 接入飞书群机器人推送通道（新增 v1.2）

描述：把已实现的飞书推送模块真正接到一个可用的群机器人上。飞书自定义机器人若启用了「签名校验」安全设置，请求必须附带按官方算法算出的签名，否则返回 19021；同时提供一条自检命令，让接入方在不生成日报、不发邮件的前提下确认通道可用。

输入：`specs/design.md` §4.4（推送层契约，v1.2 扩展）、§5 ADR-007（为什么选群机器人 Webhook）、§6.3（通道自检）

输出：`notifier/lark_bot.py`（新增 `gen_sign()` / `check()`）+ `main.py --test-lark` + `tests/test_lark_bot.py` 扩展

依赖：Task 8（飞书推送模块）、Task 9（主编排入口）

验收标准：

- [ ] `LarkBotTarget` 支持可选 `secret`；配置 `notify.lark_bot.secret` 时，载荷附带 `timestamp` 与 `sign`，算法为 `Base64(HMAC-SHA256(key=secret, msg="{timestamp}\n{secret}"))`
- [ ] 未配置 `secret` 时载荷与 v1.1 完全一致（v1.1 的测试一行不改依然全绿）
- [ ] `python main.py --test-lark` 发送一条 `msg_type=text` 的自检消息，成功返回 0、失败返回非 0，并打印人类可读的排查说明；不受 `notify.lark_bot.enabled` 开关限制
- [ ] Webhook 为空时立即提示缺失的变量名并返回非 0，不发起网络请求
- [ ] 飞书返回 19021（签名不匹配）/19024（关键词不匹配）/19001（参数错误）时，错误日志附带对应的排查提示
- [ ] 配置示例、`.env.example` 与 README 同步补充 `LARK_BOT_WEBHOOK` / `LARK_BOT_SECRET` 与接入步骤
- [ ] 单元测试覆盖签名计算、自检成功/失败、无 secret 的兼容行为

---

## Task 13: 实现工作台前端资源（新增 v2.0）

描述：编写浏览器端工作台脚本，实现表单校验、手写日报生成、两级降级的复制、本地草稿（新增 / 载入 / 复制 / 删除 / 清空）、"从自动日报载入"下拉与详情页中转，并为这些控件补上样式组件。脚本不发起任何网络请求，草稿只写浏览器 localStorage。

输入：`specs/design.md` §3（WorkbenchPayload、DraftRecord）、§4.3（站点层契约）、§6.5（工作台安全与可用性）、§5 ADR-008

输出：`generator/templates/workbench.js` + `generator/templates/style.css`（工作台组件类）

依赖：Task 6

验收标准：

- [ ] 手写日报输出固定格式：`# 工作日报 · YYYY-MM-DD` + `## 今日完成 / ## 明日计划 / ## 需要协助`，空小节写 `- 未填写`
- [ ] 日期与"今日完成"为空时给出字段级错误提示并把焦点移到第一个出错字段
- [ ] 复制优先用 Clipboard API，不可用时退回 `document.execCommand`，都失败则选中内容并提示手动复制
- [ ] 本地草稿键为 `daily-report-workbench:history:v1`，同日期覆盖旧记录、按保存时间倒序、最多保留 50 条
- [ ] 草稿支持载入、复制、删除单条与"清空全部"（二次确认）；localStorage 不可用时禁用相关操作并提示"草稿只在本次会话内有效"
- [ ] "从自动日报载入"下拉能把选定日期的自动日报填进编辑框；详情页"载入到工作台"通过 `daily-report-workbench:pending:v1` 中转后跳回 `index.html#workbench`
- [ ] 所有动态内容只用 `textContent` 与 `document.createElement` 渲染，脚本中不出现 `innerHTML`
- [ ] 脚本内不内嵌 `</script` 序列（避免内联进页面时提前闭合标签），且 `node --check` 语法校验通过

---

## Task 14: 页面接入工作台与内联载荷（新增 v2.0）

描述：把工作台接进站点页面：模板新增工作台区块（默认 `hidden`，脚本就绪后显示）、详情页操作行与脚本块；生成层把日报正文序列化为页面内联 JSON 载荷并按开关决定是否内联；配置新增逃生开关。

输入：`specs/design.md` §3（WorkbenchPayload）、§4.3（站点层契约）、§6.5

输出：`generator/templates/base.html.j2`、`generator/templates/index.html.j2`、`generator/templates/report.html.j2`、`generator/template.py`、`generator/site.py`、`shared/config.py`、`config.yaml.example`、`main.py`

依赖：Task 13

验收标准：

- [ ] `render_report_html()` 支持 `markdown` 与 `interactive` 两个仅关键字参数，默认值保证旧调用（邮件正文）行为不变
- [ ] `render_index_html()` 支持 `interactive`（默认 `True`），索引条目新增 `markdown` 字段供载荷使用
- [ ] 新增 `render_workbench_js()` 与 `render_workbench_data()`，后者把 `<`、`>`、`&` 转义为 `\uXXXX`
- [ ] `SiteConfig` 新增 `workbench` 字段，取值来自配置 `report.workbench`（默认 `true`）
- [ ] `report.workbench: false` 时索引页与详情页都不含脚本与工作台区块，页面回到 v1.x 只读形态
- [ ] 邮件正文走默认 `interactive=False`：不含 `<script`、不含"复制 Markdown"与"载入到工作台"按钮
- [ ] 站点产物仍是 `index.html`、`daily-report-<date>.html`、`assets/style.css`、`.nojekyll` 四个文件
- [ ] 索引页"从自动日报载入"下拉在服务端渲染出全部历史日期，脚本不可用时仍能看到有哪些期
- [ ] `config.yaml.example` 与 README 说明 `report.workbench` 的含义

---

## Task 15: 工作台测试与文档回归（新增 v2.0）

描述：为工作台补测试，更新受影响的站点与集成测试断言，跑全量回归并补充使用说明。

输入：`specs/design.md` §4.3、§6.5，Task 13/14 的实现

输出：`tests/test_workbench.py` + 更新后的 `tests/test_site.py`、`tests/test_integration.py` + `README.md`（工作台使用说明与隐私提示）

依赖：Task 14

验收标准：

- [ ] `tests/test_workbench.py` 覆盖：工作台 UI 元素齐全、索引页载荷含全部历史日期、`<` 已转义、`</script>` 注入不能逃逸、详情页按钮与自身载荷、邮件正文无脚本、`report.workbench: false` 时无工作台、工作台脚本静态检查（含剪贴板兜底、无 `innerHTML`）
- [ ] `tests/test_site.py` 的"Markdown 标记不残留"断言改为只检查正文区域（载荷位于末尾脚本标签内）
- [ ] `tests/test_integration.py` 的正常、降级、空数据三个场景都断言工作台存在且页面自洽
- [ ] `pytest` 全绿（v1.2 的 85 项一行不改 + 新增项全部通过）
- [ ] `node --check generator/templates/workbench.js` 通过（本仓库无 `package.json`，`npm test` 不适用）
- [ ] README 写明工作台的用法（填写 → 生成 → 复制 → 本地草稿 → 载入自动日报）、"内容不会上传"的隐私说明，以及 `report.workbench: false` 的关闭方式

---

## Task 16: 日报列出提交变更文件名（新增 v2.1）

描述：把「代码提交」板块从"只报变更文件数"升级为"列出变更文件名"。文件名来自详情端点已经返回的 `files` 数组，因此只做字段映射与渲染，不新增 API 调用。

输入：`specs/proposal.md` §2.1、§3.1（v2.1），`specs/design.md` §3（`CommitRecord.files`）、§4.1、§4.2（v2.1）

输出：`shared/models.py`、`collector/github_commit.py`、`generator/formatter.py` + 更新后的 `tests/test_github_commit.py`、`tests/test_generator.py`

依赖：Task 3、Task 6（两者均已完成）

验收标准：

- [ ] `CommitRecord` 新增 `files: tuple[str, ...]`，带默认值 `()`，未传该字段的既有调用不受影响
- [ ] `files_changed` 语义不变（仍是详情端点返回的文件数），`files` 为其文件名元组
- [ ] 详情请求失败或超出 `max_commit_details` 上限时，`files` 为空元组且提交记录本身保留
- [ ] 文件名与增删行数来自同一次详情请求，不新增任何 HTTP 请求（限流预算不变）
- [ ] 「代码提交」条目在有文件名时输出 `（+A/-D，N 个文件：f1、f2、…）`，最多 10 个，超出以 `、…` 结尾
- [ ] `files` 为空时退回 `（+A/-D，N 个文件）`，不出现空冒号
- [ ] Markdown、站点详情页与邮件正文三端显示一致（共用同一份已渲染文本，模板不改）
- [ ] 单元测试覆盖：字段完整性、详情上限、详情失败、文件名截断、无文件名回退
- [ ] `pytest` 全绿（本仓库无 `package.json`，本次不涉及 JS 改动，`npm test` 不适用）

---

## Task 17: 条目链接与任务上下文（新增 v2.2）

描述：把日报条目可点击化（提交短 SHA、Issue 编号、评论来源），给任务行补标签/指派/评论数，并在单人团队时合并重复的头部与成员标题。所有数据都取自采集器已在请求的响应，不新增 HTTP 请求。

输入：`specs/proposal.md` §2.1、§3.1（v2.2），`specs/design.md` §3、§4.1、§4.2（v2.2）

输出：`shared/models.py`、`collector/` 三个采集器、`generator/formatter.py`、`generator/template.py`、`generator/templates/report.html.j2` + 更新后的采集与生成测试

依赖：Task 3、Task 4、Task 5、Task 6

验收标准：

- [ ] 提交行输出 `[短SHA](链接)`（7 位）；缺 SHA 时整段省略，不留 `[]()` 空壳
- [ ] 任务行输出 `[#编号](链接) 标题：A → B`；缺链接时退回 `#编号`
- [ ] 协作沟通行来源带链接；缺链接时保持 `[来源]` 原样
- [ ] 任务行括号补充标签、指派与评论数，空片段不出现；指派人与本段成员一致时省略
- [ ] 站点详情页与邮件正文把 Markdown 链接渲染成 `<a>`（新窗口 + `rel="noopener"`），链接文字与 URL 分别转义，无法注入属性
- [ ] 单人团队省略成员标题并把身份并入头部 `- 团队：姓名（@username）`；多人团队行为与 v2.1 一致
- [ ] 三个采集器的新字段都有单元测试断言；`pytest` 全绿

---

## Task 18: 近 N 期趋势与对比（新增 v2.3）

描述：给日报头部加「对比上期」与「近 N 期」两行，给索引页加内联 SVG 趋势图；为此把日报统计落成 SQLite 结构化列。

输入：`specs/proposal.md` §2.1/§2.2/§3.1（v2.3），`specs/design.md` §3（`ReportStats`）、§4.2、§4.3、§6.7、ADR-009

输出：`shared/storage.py`、`shared/models.py`、`generator/formatter.py`、`generator/site.py`、`generator/template.py`、`generator/templates/index.html.j2`、`generator/templates/style.css`、`main.py` + 更新后的存储/生成/站点/集成测试

依赖：Task 2、Task 6、Task 9

验收标准：

- [ ] `reports` 表新增五个统计列；老库实例化时幂等补齐，旧行为 `NULL`
- [ ] `HistoryEntry.to_stats()` 对旧行返回 `None`，对比与趋势都会跳过而不是当 0
- [ ] 头部「对比上期（日期）：提交 ±N · 任务 ±N · 沟通 ±N · 工时 ±N.Nh」，基数取最近一期已保存日报；无历史时整行不出现
- [ ] 头部「近 N 期：提交 ▁▂▃█（合计）· 工时 ▁▂▃█（合计）」，不足 2 期不出现；全 0 序列不虚高
- [ ] 索引页在有两期及以上带统计的日报时渲染 `<svg>` 柱状图（提交数、工时），标注日期与数值；不足两期或全 0 时不渲染
- [ ] 趋势图不引入任何脚本、图表库或外部资源，`docs/` 仍是四个文件（ADR-009、§6.5）
- [ ] 邮件正文与飞书卡片自动带上头部两行（与 Markdown 共用 `extra_lines`）
- [ ] `pytest` 全绿，并覆盖迁移、sparkline 边界、对比行、SVG 渲染与"无历史不出现"

---

## Task 19: 飞书群消息只读数据源（新增 v2.3）

描述：新增企业自建应用读取指定群的会话历史，只产出"条数与发言人数"，正文就地丢弃。

输入：`specs/proposal.md` §2.1/§2.2/§3.1（v2.3），`specs/design.md` §2、§3（`ChatSummaryRecord`）、§4.1、§6.6

输出：`shared/http.py`（`FeishuClient`）、`collector/feishu_message.py`、`shared/config.py`、`main.py`、`config.yaml.example`、`.env.example` + `tests/test_feishu_message.py` 与集成测试

依赖：Task 2、Task 5（讨论采集的过滤口径）、Task 9

验收标准：

- [ ] 配置新增 `sources.feishu`（`enabled`/`app_id`/`app_secret`/`base_url`/`chats[id,name]`/重试与超时），默认 `false`
- [ ] `enabled: true` 但凭据为空时，`--check` 报出缺失的环境变量名；`enabled: true` 但没有 `chats` 时启动即报配置错误
- [ ] 未启用时采集器不发起任何请求，采集计划里也没有这一项（日报与 v2.2 完全一致）
- [ ] `tenant_access_token` 单次运行只取一次；`code != 0` 与 HTTP 4xx/5xx 都按失败处理并重试后抛 `CollectorError`
- [ ] 只统计 `sender_type=user` 且非 `system` 的消息，按左闭右开窗口二次裁剪 `create_time`
- [ ] 产出 `ChatSummaryRecord`（群名 / 条数 / 发言人数），模型里没有内容字段，产物与日志里搜不到消息正文
- [ ] 日报头部出现 `- 飞书群：群名 N 条 · M 人发言`，数据源徽章出现 `飞书消息 N 条`（N 为消息总条数）
- [ ] 飞书源失败只标记该源失败，其它数据源与推送不受影响；`--check` 增加飞书 token 检查
- [ ] 全部使用 `httpx.MockTransport`，不访问真实网络；`pytest` 全绿

---

## Task 20: 数据来源标注与日报可读性改进（新增 v2.4）

描述：给所有对外产物末尾追加统一格式的三要素来源标注（数据源全称 / 采集时间 / 授权使用范围），同时修掉日报页面在手机端的五处可读性问题。

输入：`specs/proposal.md` §2.1（数据来源标注、静态日报站可读性）/§3.1，`specs/design.md` §3（`DataSourceRef`）、§4.2、§4.3、§4.4、§6.8、ADR-010

输出：`shared/models.py`（`DataSourceRef`、`DailyReport.attribution`）、`shared/config.py`（`report.attribution`）、`generator/formatter.py`（`build_attribution`、标题分级、头部拆行、空板块合并、提交 `entries`、趋势门槛）、`generator/templates/*`、`notifier/lark_bot.py`（截断保留标注）、`main.py`（`_source_refs`）、`config.yaml.example` + `tests/test_attribution.py`

依赖：Task 2、Task 6、Task 8

验收标准：

- [ ] 配置新增 `report.attribution.enabled`（默认 `true`）与 `report.attribution.scope`（默认「仅限团队内部日报展示」）
- [ ] 标注整行固定为 `数据来源：<各源全称> ｜ 采集时间：YYYY-MM-DD HH:MM（时区）｜ 授权范围：<scope>`，三要素齐全且顺序不变
- [ ] 四处末尾都出现同一行标注：邮件 Markdown、邮件 HTML、飞书卡片 payload、站点详情页与索引页
- [ ] 数据源全称只列本次实际参与采集的源（GitHub 仓库 / 飞书群 / 飞书任务），未启用的源不出现
- [ ] `source_refs` 为空（关闭开关）时，四处都不出现标注，其余产物逐字不变；改 `scope` 后四处同步变化
- [ ] 飞书卡片正文超长被截断时，标注行仍完整保留在末尾，总长度不超 `MAX_MARKDOWN_LENGTH + 40`
- [ ] 正文大标题不再带日期（`<h1>` 与 Markdown 首行），日期出现在头部 `- 日期：` 行；`<title>` 仍保留完整标题
- [ ] 同一份日报里 ≥ 2 个内容板块为空时合并成一行 `今日无记录：板块 A、板块 B`；工时统计与飞书任务不参与合并；只剩 1 个空板块时保留原样
- [ ] 趋势行与索引页 SVG 趋势区块的门槛同步改为 3 期；2 期时两处都不出现
- [ ] HTML 侧提交行为两行（主行 + 元信息行），Markdown 与飞书卡片仍是单行
- [ ] 既有断言按新形态更新，`pytest` 全绿；新建 `tests/test_attribution.py` 覆盖三要素、关闭开关、截断保留、四处一致性

---

## Task 21: 飞书任务状态同步（新增 v2.4）

描述：新增只读采集器读取飞书工作台任务快照，在「任务进展」板块下新增子小节，按"已完成 / 进行中 / 未开始"三态展示。本期不做定时刷新（快照口径，见 design.md ADR-011）。

输入：`specs/proposal.md` §2.1（飞书任务状态同步）/§2.2/§3.1，`specs/design.md` §2、§3（`FeishuTaskRecord`）、§4.1、§4.2、§6.1、§6.8、ADR-011

输出：`collector/feishu_task.py`、`shared/models.py`（`SOURCE_FEISHU_TASK`、`STATUS_NOT_STARTED`、`FeishuTaskRecord`）、`shared/config.py`（`sources.feishu.tasks`）、`generator/formatter.py`（`_feishu_task_section`）、`main.py`、`config.yaml.example` + `tests/test_feishu_task.py` 与集成测试

依赖：Task 2、Task 6、Task 19（复用 `FeishuClient` 与 `build_client`）

验收标准：

- [ ] 配置新增 `sources.feishu.tasks`（`enabled`/`scope: all|tasklist`/`tasklist_guids`/`max_tasks`），默认 `false`；`scope: tasklist` 但清单为空时启动即报配置错误
- [ ] 未启用时采集器不发任何请求，日报里不出现任何飞书任务字样（产物与 v2.3 逐字一致）
- [ ] 三态映射：`completed_at` 非空且非 `0` → 已完成；未完成且开始时间在未来 → 未开始；其余未完成 → 进行中；无 `start` 字段时退化为"未完成即进行中"
- [ ] 日报「任务进展」下出现子小节 `任务进展 · 飞书任务`，只渲染一次（挂在第一个成员上）；首行给快照时间与三态计数，逐条 `状态 · 标题（截止日期）`
- [ ] 排序 `进行中 → 未开始 → 已完成`，组内按截止日期升序；最多 20 条，超出追加"其余 N 条见飞书任务"，计数仍报全量
- [ ] 目标日期 ≠ 生成当天时标题带「补跑快照」；任务为空显示"飞书工作台暂无任务"；源失败显示"飞书任务数据获取失败（原因）"
- [ ] 权限错误 `99991672` 被翻译成"补 `task:task:read` / `task:tasklist:read` 权限并重新发布"的可执行提示，不把原始英文报文塞进日报
- [ ] 任务描述字段不进入模型、产物与日志；不对飞书做任何写操作
- [ ] 该源失败只标记该源失败，其它数据源、日报生成、站点渲染与推送都不受影响
- [ ] 全部使用 `httpx.MockTransport`，不访问真实网络；`pytest` 全绿；真机验证需先在开发者后台补权限并重新发布（未补权限时以"可执行提示"形态通过）

---

## Task 22: 工时口径扩展到活动时间（新增 v2.7）

描述：把工时推导的输入从"提交时间"扩到"活动时间"——提交、Issue 状态变更、评论三类时间戳合成一条活动流，仍用同一套会话法；同步放宽降级规则并更新对外口径文案。

输入：`specs/proposal.md` §2.1（工时统计）/§3.1，`specs/design.md` §4.2（工时推导契约）、§6.4、ADR-013

输出：`generator/hours.py`、`generator/formatter.py`（`_derive_work_hours` / `_hours_section`）、`shared/models.py`（`WORK_HOURS_NOTE`、`WorkHoursRecord`）+ `tests/test_hours.py`、`tests/test_generator.py`、`tests/test_integration.py`

依赖：Task 2、Task 6、Task 7、Task 11

验收标准：

- [ ] `derive()` 新增仅关键字参数 `tasks=()`、`messages=()`，默认空时行为与 v1.1 完全一致（既有 12 个工时用例不改动即通过）
- [ ] 三类活动都能推进工时：单独只有任务、或单独只有评论时都能得出非 0 结果
- [ ] 三类活动按 `author` / `assignee` / `sender` 归属到成员，未匹配身份不计入；窗口外活动被忽略
- [ ] 会话法参数不变（间隔 > 60 分钟切段、每段 +0.5h 收尾、0.5h 网格、单日 12h 上限），跨自然日活动各自成段
- [ ] `WorkHoursRecord` 带 `commit_count` / `task_count` / `comment_count` / `activity_count`；`detail` 为"提交 x · 任务 y · 评论 z，N 个工作段"且**只列非零类别**
- [ ] 板块行输出 `- 工时：2.5h（提交 1 · 任务 1 · 评论 1，1 个工作段）`；头部口径说明为"按提交/任务/评论时间推导，非真实考勤"，三端同源
- [ ] 降级放宽：只有**三个活动源全部失败**才输出"工时数据不可用（原因）"；单个源失败时用成功源推导，失败源仍由头部徽章标注
- [ ] 全量 `pytest` 全绿；真机 `--dry-run` 核对工时行与说明文字

---

## Task 23: 团队管理摘要与在线日报入口（新增 v2.8）

描述：在成员四板块之前增加团队级管理摘要，按确定性规则输出今日概览、需要关注和下一步，并通过可选站点根地址为邮件与飞书提供当天在线日报入口。邮件、站点详情页与飞书卡片共用同一份视图内容。

输入：`specs/proposal.md` §2.1（管理摘要）/§3.1，`specs/design.md` §3（`DailyReport.public_url`）、§4.2、ADR-014

输出：`shared/config.py`（`report.public_base_url`）、`shared/models.py`（`DailyReport.public_url`）、`generator/formatter.py`（管理摘要与 Markdown）、`generator/templates/report.html.j2`、`generator/templates/email.html.j2`、`generator/templates/style.css`、`main.py`、`config.yaml.example`、`README.md` + 生成层/邮件/站点/配置测试

依赖：Task 2、Task 6、Task 7、Task 8、Task 21、Task 22

验收标准：

- [ ] 管理摘要位于成员四板块之前，邮件、站点详情页与飞书卡片（Markdown 内容）均可见
- [ ] 「今日概览」输出飞书三态与逾期数、GitHub 提交/增删/文件/Issue/互动汇总；重点进展最多 3 条，顺序为飞书完成 → Issue 完成 → 最新提交
- [ ] 「需要关注」覆盖逾期、当天和未来第 3 天到期的未完成飞书任务，未来第 4 天不纳入；最多 5 条；所有失败数据源始终列出
- [ ] 「下一步」最多 3 条，按进行中优先、截止日期升序排列；排除需要关注中已经出现的任务
- [ ] 配置 `report.public_base_url` 后生成当天详情页链接；邮件显示文内按钮、飞书卡片显示 Markdown 链接；配置为空或网页详情页本身都不重复显示入口
- [ ] 日期边界按日报目标日计算，补跑历史日期不会使用生成当天作为基准
- [ ] 邮件模板继续保持无 `<style>`、无 `class`、无 CSS 变量、无 flex/grid/clamp；链接按既有过滤器转义
- [ ] 空数据、只有任务、只有提交、失败数据源、任务超限等分支均有单测；全量 `pytest` 全绿，并完成 `--dry-run --date 2026-10-20` 真机核对

---

## 执行顺序

推荐执行顺序（考虑依赖关系和并行机会）：

- 阶段 1：Task 1（项目初始化）
- 阶段 2：Task 2（共享基础层）
- 阶段 3：Task 3 + Task 4 + Task 5 并行（三个采集模块）
- 阶段 4：Task 11（工时推导模块，v1.1 新增）
- 阶段 5：Task 6（日报生成与站点渲染，含工时板块）
- 阶段 6：Task 7 + Task 8 并行（两个推送模块）
- 阶段 7：Task 9（主编排入口）
- 阶段 8：Task 10（集成测试）
- 阶段 9：Task 12（接入飞书群机器人：签名校验 + 自检，v1.2 新增）
- 阶段 10：Task 13（工作台前端资源：脚本与样式组件，v2.0 新增）
- 阶段 11：Task 14（页面接入工作台与内联载荷，v2.0 新增）
- 阶段 12：Task 15（工作台测试、全量回归与 README，v2.0 新增）
- 阶段 13：Task 16（日报列出提交变更文件名，v2.1 新增）
- 阶段 14：Task 17（条目链接与任务上下文，v2.2 新增）
- 阶段 15：Task 18（近 N 期趋势与对比，v2.3 新增）
- 阶段 16：Task 19（飞书群消息只读数据源，v2.3 新增）
- 阶段 17：Task 20（数据来源标注与日报可读性改进，v2.4 新增）
- 阶段 18：Task 21（飞书任务状态同步，v2.4 新增；不需定时刷新，见 design.md ADR-011）
- 阶段 19：Task 22（工时口径扩展到活动时间，v2.7 新增）
- 阶段 20：Task 23（团队管理摘要与在线日报入口，v2.8 新增）
