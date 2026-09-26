# 智能日报生成器 — 任务清单

## 元信息

- 关联规范：`specs/proposal.md`、`specs/design.md`
- 任务总数：12（v1.1 新增 Task 11，v1.2 新增 Task 12）
- 预计总执行时间：3 到 4h（包含测试）
- 执行策略：按依赖关系顺序执行，独立任务可并行执行
- 相对书中的扩展点：书中采集层为 GitHub + 飞书任务 + 飞书消息，本期改为三个 GitHub 采集器（Task 3/4/5）；书中无静态站，本期把站点渲染并入生成层（Task 6）并在 Task 1 落地 `docs/` 与 Pages 基础文件。

## 变更记录

| 版本 | 变更类型 | 内容 |
| --- | --- | --- |
| v1.0 | 首版 | Task 1–10（见下方） |
| v1.1 | 需求变更 | 新增 Task 11「实现工时推导模块」；修改 Task 6 验收标准（新增工时板块与布局顺序）；执行顺序插入"阶段 4：Task 11 → 阶段 5：Task 6" |
| v1.1.1 | 缺陷修复 | 密钥注入失效：程序未加载 `.env`（只读系统环境变量），占位符空值未视为缺失；修复后 Task 9 补充两条验收标准 |
| v1.2 | 需求澄清 | 新增 Task 12「接入飞书群机器人」；修改 Task 8 验收标准（新增签名校验与自检）；执行顺序追加"阶段 9：Task 12" |

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
- [ ] 全部模块包含对应单元测试，测试通过

---

## Task 3: 实现 GitHub 提交采集模块

描述：调用 GitHub REST API 获取指定仓库在采集窗口内的 Commit 记录（含变更统计），返回 `CommitRecord` 列表。

输入：`specs/design.md` §3（CommitRecord 数据模型）、§4.1（采集层接口契约）

输出：`collector/github_commit.py` + `tests/test_github_commit.py`

依赖：Task 2

验收标准：

- [ ] `collect()` 函数签名符合 design.md §4.1 的接口定义
- [ ] 返回的每个 `CommitRecord` 包含全部 7 个字段且类型正确
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
- [ ] 日报头部显示团队总工时与人均工时，并带口径说明"按提交时间推导，非真实考勤"
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
