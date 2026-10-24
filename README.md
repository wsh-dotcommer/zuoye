# 智能日报生成器（SDD 复现 · 作业二）

依据《SDD 实战：规范驱动开发之道》第 4–6 章的贯穿项目，按
`proposal → design → tasks → code → verification` 走完一次规范驱动开发。
数据源**只使用 GitHub**：Commits 当"代码提交"、Issues 状态流转当"任务进展"、
PR/Issue 评论用于工时推导与互动统计；飞书只作为推送通道。在书中范围之上增加了一项扩展：
**输出可发布的静态日报站**（GitHub Pages）。

规范文档在 [`specs/`](specs/) 下，是本次开发的唯一事实来源：

- `specs/proposal.md`：背景、范围（做什么/不做什么）、验收标准、术语
- `specs/design.md`：管道架构、模块职责、数据模型、接口契约、ADR、非功能性约束
- `specs/tasks.md`：12 个可验收任务与 9 阶段执行顺序（v1.1 加工时、v1.2 加飞书接入）

## 快速开始

```powershell
# 1. 安装依赖（Python 3.11+）
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

# 2. 生成自己的配置
Copy-Item config.yaml.example config.yaml    # 按需修改仓库与成员映射
Copy-Item .env.example .env                  # 按需填入凭据（.env 已被 gitignore）

# 3. 体检：配置、环境变量、GitHub / SMTP / 飞书 Webhook / 飞书群消息数据源
.\.venv\Scripts\python.exe main.py --check

# 4. 干跑：采集 + 生成 + 站点渲染，不推送
.\.venv\Scripts\python.exe main.py --dry-run

# 5. 正式运行（默认采集当日 00:00 → 现在）
.\.venv\Scripts\python.exe main.py
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--date 2026-09-18` | 补跑历史某日（窗口为该日整天） |
| `--since 2026-09-01 --until 2026-09-26` | 自定义采集窗口 |
| `--dry-run` | 只生成不推送 |
| `--check` | 只体检，不采集、不推送 |
| `--test-lark` | 只往飞书群发一条自检消息，不采集、不生成、不发邮件 |

## 命令速查表：这条命令会不会发消息？

**核心规则：加 `--dry-run` 就一条推送都不发；不加就会按 `notify` 开关发邮件 / 推飞书。**

| 命令 | 采集 | 生成日报 | 渲染站点 | 发邮件 / 推飞书 |
| --- | --- | --- | --- | --- |
| `main.py --config config.yaml` | 当天 00:00 → 现在 | ✅ | ✅ | ✅ 按开关发 |
| `main.py --config config.yaml --date 2026-09-26` | 指定那整天 | ✅ | ✅ | ✅ 按开关发 |
| `main.py --config config.yaml --dry-run` | 当天到现在 | ✅ | ✅ | ❌ 只预览 |
| `main.py --config config.yaml --dry-run --date 2026-09-26` | 指定那整天 | ✅ | ✅ | ❌ 只预览 |
| `main.py --config config.yaml --check` | 不采集 | ❌ | ❌ | ❌ 只体检 |
| `main.py --config config.yaml --test-lark` | 不采集 | ❌ | ❌ | ⚠️ 只发一条飞书自检消息 |

当前推送开关（`config.yaml` 的 `notify` 段）：

```yaml
notify:
  email:     { enabled: true }    # true → 不加 --dry-run 就会发邮件
  lark_bot:  { enabled: false }   # true → 不加 --dry-run 就会推飞书群
```

飞书那条不受开关限制的例外是 `--test-lark`：它专为"通道到底通不通"设计，无论
`enabled` 是 true 还是 false，都只发一条纯文本自检消息（详见下方「接入飞书群机器人」）。

其他要点：

- **工作日**：直接跑 `main.py --config config.yaml` 即可（采集"今天到现在"）。**周末/节假日**会被自动跳过，要看那天就显式加 `--date YYYY-MM-DD`。
- `--date` 后面**必须跟日期**，不能只写 `--date`。
- 同一日期重复运行是**幂等覆盖**：`output/`、`docs/`、SQLite 都是按日期更新，不会产生重复记录。
- 推荐的日常节奏：先 `--dry-run` 看内容对不对 → 确认后再去掉 `--dry-run` 正式发。

## 产物

- `output/daily-report-<日期>.md` 与 `.html`：当日报表的两种形态
- `docs/index.html`：静态日报站索引页；`docs/daily-report-<日期>.html` 详情页
- `docs/assets/style.css`、`docs/.nojekyll`：站点静态资源
- `data/reports.sqlite3`：日报历史（按日期幂等覆盖）
- `logs/daily-report.jsonl`：JSON Lines 执行日志（开始时间、各数据源条数、推送结果、结束时间）

> v2.0 起索引页与详情页内联了「日报工作台」脚本与数据，产物仍是上面这四个文件，没有新增
> 任何服务端接口；页面本身也不联网（详见下一节）。

## 日报工作台（v2.0）

索引页顶部多了一个工作台，用来把"自动日报之外的部分"补起来；日报详情页顶部多了两个按钮。

| 在哪里 | 能做什么 |
| --- | --- |
| 索引页 · Step 01 | 填日报日期、今日完成（必填）、明日计划、需要协助；也可以"从自动日报载入"某一期再改 |
| 索引页 · Step 02 | 生成一份 Markdown 日报，内容可自由编辑，点「复制日报」直接粘贴到飞书/邮件 |
| 索引页 · Step 03 | 生成的草稿自动存在本机浏览器，可载入、复制、删除单条或清空全部（最多 50 条） |
| 日报详情页 | 「复制 Markdown」复制这一期的自动日报原文；「载入到工作台」把它送进索引页编辑框继续改 |

手写日报的格式固定为 `# 工作日报 · 日期` + `## 今日完成 / ## 明日计划 / ## 需要协助`，
留空的小节写「未填写」，不会替你猜测内容。

三个必须知道的边界：

- **内容不会上传**：填写的东西只存在你自己浏览器的 localStorage，不写回 GitHub、不进数据库、不会推送到飞书或邮箱。换台电脑或换个浏览器就看不到。
- **页面不联网**：工作台不请求 GitHub、不新增接口、不引入第三方脚本，所以"点一下生成当天真实数据"做不到——真实数据仍然只能由 `main.py` 在本地采集。
- **脚本/存储不可用时自动退化**：禁用 JavaScript 时页面就是原来的只读日报站；隐私模式下仍能生成与复制，只是提示"草稿只在本次会话内有效"。

不想要这个工作台？把 `config.yaml` 的 `report.workbench` 改成 `false` 重新生成，页面就回到 v1.x 的纯只读形态：

```yaml
report:
  workbench: false      # 生成不含任何脚本的纯只读站点
```

## 工时统计口径（v1.1 引入，v2.7 扩展）

日报里的"工时统计"由 **GitHub 活动时间推导**（不接考勤系统、不需要成员填报），算法叫会话法。v2.7 起"活动"包含三类痕迹：

| 活动 | 取谁 | 取哪个时间 |
| --- | --- | --- |
| 提交 | 提交作者 | 提交时间 |
| Issue 状态变更 | 变更的操作人 / 指派对象 | 那次状态变更发生的时刻（不是 Issue 的最后更新时间） |
| 评论 | 评论者 | 评论时间 |

三类时间戳合成**一条活动流**，再跑同一套规则：

| 规则 | 默认值 | 配置项 |
| --- | --- | --- |
| 相邻活动间隔超过多久算新的工作段 | 60 分钟（等于阈值不算） | `hours.gap_minutes` |
| 每个工作段的收尾时长（只有一条活动的段按此计） | 0.5h | `hours.wrap_up_hours` |
| 结果四舍五入到的网格 | 0.5h | `hours.rounding_hours` |
| 单人单日上限 | 12h | `hours.daily_cap_hours` |
| 是否显示工时板块 | 显示 | `hours.enabled` |

计算方式：按自然日（`team.timezone`）把活动分到各天 → 切分工作段 → 每段时长 = 末次 − 首次 + 收尾 → 逐日封顶 → 按网格四舍五入 → 汇总。板块行只列非零类别，例如 `- 工时：2.5h（提交 1 · 任务 1 · 评论 1，1 个工作段）`。

几个必须知道的口径：

- **它是推导值，不是考勤值**。开会、写文档、读代码（没有落成 commit / 任务变更 / 评论的部分）都不会被计入，日报头部固定标注"按提交/任务/评论时间推导，非真实考勤"。
- **口径变更不回溯**：v2.7 之前生成的日报仍是旧口径数字，所以「近 N 期」趋势与「对比上期」会出现一次跳变——这是口径变更的必然结果，不是 bug。想让历史也统一，只能删掉 `data/reports.sqlite3` 后逐日重跑。
- 成员当天没有任何活动 → `工时：0h（今日无记录）`；**三个活动源全部失败**才显示 `工时数据不可用（原因）`。只有一个源失败时仍会出数字（偏低），失败的数据源会在头部徽章里标红。
- 推导是本地纯计算，不产生任何额外的 GitHub API 请求，也不影响限流预算。
- 想让数字更贴近真实节奏，就调 `hours.gap_minutes`（例如团队习惯一次提交间隔两小时，就调成 120）。

## 提交变更文件名（v2.1）

日报「代码提交」的每条记录会在数量后面列出这次提交动了哪些文件：

```
- `wsh-dotcommer/zuoye` Add files via upload（+1/-0，1 个文件：README.md）
```

三个口径：

- 一条提交最多列 **10 个**文件名，超出时在第 10 个后补 `、…`；前面的"12 个文件"仍是真实总数。
- 文件名与增删行数来自**同一次**提交详情请求，不额外发起请求，也不影响 GitHub 限流预算。
- 受 `sources.github.max_commit_details`（默认 100）约束：超出预算的提交取不到详情，条目退回只报数量的旧格式；详情请求失败的提交同理。

## 条目链接与任务上下文（v2.2）

日报的每条记录都能点进 GitHub 对应页面：

```
- `wsh-dotcommer/zuoye` [df70d04](https://github.com/wsh-dotcommer/zuoye/commit/df70d04…) Add files via upload（+1/-0，1 个文件：.abc.txt）
- [#3](https://github.com/wsh-dotcommer/zuoye/issues/3) test：进行中 → 已完成（1 条评论）
- [wsh-dotcommer/zuoye #3](https://github.com/wsh-dotcommer/zuoye/issues/3#issuecomment-…) wsh-dotcommer：测试邮箱
```

四条口径：

- 链接与上下文信息（短 SHA、Issue 编号、评论地址、标签、评论数）都取自采集时**已经在请求**的同一批 GitHub 响应，不额外发请求。
- 任务行括号里依次是「标签、指派、评论数」；没有的项不显示，指派人与该段落成员相同时也不重复写名字。
- 缺链接时提交行只留短号、任务行只留 `#编号`；两者都没有时整段省略，不会出现空的 `[]()`。
- 团队只有一位成员时，头部写成 `- 团队：姓名（@username）` 并省略重复的成员标题；多人团队保持原样。

站点页与邮件里这些是真正的 `<a>` 链接（新窗口打开），飞书卡片由 `lark_md` 渲染同一串 Markdown 链接。

## 趋势与对比（v2.3）

日报头部会多出两行（有历史数据时才出现）：

```
- 对比上期（2026-10-01）：提交 +7 · 任务 +1 · 沟通 +1 · 工时 +0.5h
- 近 7 期：提交 ▁▂▃▅▂▃█（25 条） · 工时 ▁▂▃▅▂▃█（6.5h）
```

- 「对比上期」的基数是**上一期已生成的日报**（不是严格的"昨天"）：周末与节假日不生成日报，写死昨天会经常没有基准。
- 「近 N 期」最多 7 期，用 8 档块字符画迷你趋势；**含当日在内的期数不足 3 期时不显示**（v2.4 起由 2 期调高：两期合计容易被误读成"今天的数"）。
- 站点索引页会多出一个"近 N 期趋势"区块，两张手写内联 SVG 柱状图（提交数、工时）。**零 JS、零外部资源**，禁用脚本也能看。
- 这些数字来自 `data/reports.sqlite3` 新增的结构化统计列，不再需要解析 Markdown；老库会在启动时自动补齐这些列，旧记录显示为"无可比数据"（跳过，不按 0 计算）。

## 管理摘要（v2.8）

日报会在成员板块之前增加一块团队级「管理摘要」，邮件、站点详情页和飞书卡片都会同步出现：

- **今日概览**：飞书任务的已完成 / 进行中 / 未开始 / 逾期数量，GitHub 提交数与增删行数、涉及文件数、Issue 完成/推进数、互动数；重点进展最多 3 条。
- **需要关注**：已逾期、当天到期和未来 3 天内到期的未完成飞书任务，按截止日期排序，最多 5 条；数据源采集失败也会在这里明确列出。
- **下一步**：进行中任务优先，其次按截止日期排列，最多 3 条；不会重复列出“需要关注”里的任务。

摘要全部用现有数据按固定规则计算，**不调用 AI、不新增数据请求**。日期边界按日报目标日计算，补跑历史日期也使用那一天。

可选的在线日报入口由 `report.public_base_url` 控制：

```yaml
report:
  public_base_url: https://wsh-dotcommer.github.io/zuoye
```

非空时，邮件顶部出现“查看当天完整日报”按钮，飞书卡片带当天详情页链接；留空时两处都不显示。网页详情页本身就是在线日报，因此不重复放入口。

## 把飞书群消息接入日报（v2.3）

飞书在这里的角色多了一个：除了推送，还可以**只读地**统计指定群的活跃度（**只统计条数与发言人数，不采集正文**）。

前提：群自定义机器人只能写不能读，所以读取需要**企业自建应用**。

1. 打开 [open.feishu.cn](https://open.feishu.cn) 开发者后台 → 创建**企业自建应用** → 拿到 `App ID` 与 `App Secret`。
2. 权限管理里开通读取群消息的权限（`im:message` / `im:message:readonly` 一类，视当期权限命名而定），并按提示完成发布或管理员审批。
3. 把应用机器人**加进目标群**，并拿到群的 `chat_id`（`oc_` 开头）。
4. 填凭据与群号：
   ```
   # .env
   FEISHU_APP_ID=cli_xxxxxxxx
   FEISHU_APP_SECRET=xxxxxxxx
   ```
   ```yaml
   # config.yaml
   sources:
     feishu:
       enabled: true
       chats:
         - id: oc_xxxxxxxxxxxxxxxx
           name: 智能日报
   ```
5. 体检：`main.py --check` 会多一条 `check_feishu`，能拿到 `tenant_access_token` 就算通过。
6. 正常跑一天，日报头部会出现 `- 飞书群：智能日报 12 条 · 3 人发言`，数据源徽章多一条 `飞书消息 12 条`。

四件必须知道的事：

- **正文永不落盘**：采集器只数条数与发言人数，消息内容不写模型、不进 SQLite、不进 `logs/`，也不进任何页面。`docs/` 发布后是公开页面，这一点没有开关可放宽。
- **默认关闭**：`enabled: false` 时采集计划里没有这一项，程序行为与 v2.2 完全一致。
- **失败只影响自己**：权限被收回或群被解散，只会让"飞书消息"这一路显示"数据获取失败"，不影响 GitHub 数据与推送。
- **机器人发言与系统消息不计入**：统计口径是"真人发的普通消息"。

## 把飞书任务同步进日报（v2.4）

日报「任务进展」板块下会多出一个小节，展示飞书工作台任务的**当前状态**：

```
### 任务进展 · 飞书任务
- 截至 2026-10-13 20:12 · 共 6 条：进行中 2 · 未开始 1 · 已完成 3
- ● 进行中 · 补集成测试（截止 2026-10-20）
- ○ 未开始 · 写验收文档
- ✓ 已完成 · 静态日报站上线（截止 2026-10-15）
```

配置：

```yaml
sources:
  feishu:
    tasks:
      enabled: true        # 应用需先加权限，见下
      scope: all           # all = 应用可见的全部任务；tasklist = 只同步指定清单
      tasklist_guids: []   # scope: tasklist 时必填
      max_tasks: 200
```

启用前必须先在飞书开发者后台补权限，否则接口会返回 `99991672`：

1. 打开 `https://open.feishu.cn/app/<你的 App ID>/auth?q=task:task:read,task:tasklist:read&token_type=tenant`；
2. 勾选 `task:task:read` 与 `task:tasklist:read`；
3. **重新发布一版应用**（和上次加群消息权限一样的流程）——只勾权限不发布不生效；
4. 用 `main.py --check` 验证：日志里出现 `check_feishu_tasks` 且 `count` 不为空即可。

### 还要做一次用户授权（v2.5，读「我负责的」任务必须做）

飞书的任务接口区分**身份**：应用身份（`tenant_access_token`）下的"我负责的"指的是**应用自己**，所以应用身份永远读不到你个人账号里的任务——权限开得再全也一样。要读个人任务必须拿到**用户身份令牌**，而这只能由你本人在浏览器里点一次「授权」。

一次性配置（两分钟）：

1. 开发者后台 **安全设置 → 重定向 URL**，加一条 `http://localhost:8765/callback`（只加这一条，按提示保存即可，不用重新发布）；
2. 把 `task:task:read`、`task:tasklist:read` 的**用户身份**版本也开通（权限管理页里同一个权限名会有「用户身份」和「应用身份」两条，两个都要），然后**重新发布版本**；
3. 在项目目录运行授权脚本，浏览器会自动打开，点「授权」即可：

   ```
   .\.venv\Scripts\python.exe authorize-feishu.py
   ```

   成功后令牌写入 `data/feishu-user-token.json`（`data/` 已被 gitignore，不会进版本库）。脚本还支持 `--status`（看令牌状态）、`--print-url`（只打印链接，不自动开浏览器）、`--clear`（清除令牌）。

**如果点了「授权」之后没反应**（浏览器跳回 `localhost` 失败最常见），用手动模式绕开本机回调：

```
.\.venv\Scripts\python.exe authorize-feishu.py --manual
```

它在浏览器里打开授权链接，你点完「授权」后，浏览器地址栏会跳到 `http://localhost:8765/callback?code=...`——页面显示"无法访问"是**正常的**（因为我们没在监听）。把**地址栏整条链接**复制粘回终端就行，只粘 code 也可以。粘进来的内容里如果带 `error=`，脚本会直接告诉你是"重定向 URL 没登记"还是"权限没开"，不用自己猜。

授权一次的有效期：`refresh_token` 30 天，程序会在每次运行时自动续期并写回文件，所以你不用天天授权。**30 天没跑过日报**才需要重新授权一次。

四件必须知道的事：

- **这是快照，不是实时同步**：状态取"生成日报那一刻"的值，小节标题里写明了快照时间。本期**不做定时刷新**（也正因如此不会额外消耗 GitHub 限流预算）。想看最新状态，重跑一次日报即可：`main.py --config config.yaml --dry-run` 只更新本地页面、不发邮件不推卡片。
- **三态怎么判定**：`completed_at` 有值 → 已完成；未完成但开始时间在未来 → 未开始；其余未完成 → 进行中。飞书没给开始时间的任务一律算进行中。
- **只列"当天还有意义"的任务**（v2.5.2）：未完成的全部保留（进行中 / 未开始 / 逾期未完成），**已完成只保留当天完成的**——昨天及更早完成的不再出现，日报不会一天天变长。分界是日报目标日的 00:00（北京时间），补跑历史日期时按那一天算；被隐藏的条数记在 `logs/daily-report.jsonl` 的 `feishu_tasks_filtered` 里。
- **只读且最小字段**：只取标题、状态、截止时间，任务描述与评论不采集、不落盘、不进日志；程序不会对飞书任务做任何写操作。
- **失败只影响自己**：没加权限时该小节显示"飞书任务数据获取失败（补 `task:task:read` / `task:tasklist:read` 权限并重新发布）"，其它板块与推送不受影响。

## 数据来源标注（v2.4）

所有**对外**产物末尾都会追加一行统一格式的溯源信息：

```
数据来源：GitHub 仓库 wsh-dotcommer/zuoye、飞书群 sh、飞书任务 ｜ 采集时间：2026-10-13 20:12（北京时间） ｜ 授权范围：仅限团队内部日报展示
```

- 四个地方都会出现：邮件正文（纯文本 + HTML）、飞书群卡片、站点日报详情页、站点索引页页脚，文案完全同源。
- 三要素固定为**数据源全称 / 采集时间 / 授权使用范围**；数据源全称按本次**实际启用**的源动态生成，没启用的源不会写进去。
- 想改授权口径就改 `report.attribution.scope`（默认"仅限团队内部日报展示"）；确实不需要溯源时把 `report.attribution.enabled` 改成 `false`，四处标注一起消失。
- 飞书卡片正文超过 4000 字符被截断时，标注行会**保留在末尾**，不会被截掉。

## 发布静态日报站（GitHub Pages）

1. 把项目推到 `https://github.com/wsh-dotcommer/zuoye.git`（至少包含 `docs/` 目录）；
2. 仓库 **Settings → Pages**；
3. Source 选 **Deploy from a branch**，分支选 **main**，目录选 **/docs**，保存。

几十秒后访问 `https://wsh-dotcommer.github.io/zuoye/` 即可看到索引页。

> 隐私提醒：`docs/` 一旦推送即为公开页面，日报含成员姓名与提交信息。
> 不接受公开时，把 `config.yaml` 的 `report.site_dir` 改成 `output` 即可只在本地预览
> （本地打开 `output/index.html`，或用 `python -m http.server` 起个临时服务）。

## 用别人的仓库还是自己的仓库？

两者都支持，改 `config.yaml` 的 `repos` 即可：

- **自己的仓库**：把 `repos` 写成 `owner/name`，在 `members` 里登记成员
  （`github_username` + 可选的 `github_emails`，邮箱用于匹配那些没绑定 GitHub 账号的提交）。
  仓库为空或当天没动静也走得通：日报会如实显示"今日无记录"，而不是报错；
  同一成员有多个内容板块为空时会合并为"部分板块无记录"并列出具体板块，其他有数据的板块照常显示。
- **别人的公开仓库**：直接换成对方的 `owner/name`。因为里面的作者不在你的成员表里，
  把 `sources.github.include_others` 打开，未映射作者会自动单独成段；
  机器人账号（`dependabot[bot]`、`github-actions[bot]` 等）默认被 `exclude_bots` 排除。
  公开大仓库请求量大，建议同时收紧 `max_commit_details` 与 `max_issue_timelines`。

仓库还没有内容时，可以用自带的演示配置先跑通"各数据板块都有真实数据"的效果：

```powershell
Copy-Item config.demo.yaml.example config.demo.yaml
.\.venv\Scripts\python.exe main.py --config config.demo.yaml --dry-run `
  --since 2026-09-25T00:00:00 --until 2026-09-25T18:00:00
```

（演示配置采集的是 `openai/openai-python` 当天的真实公开数据；改用 `config.yaml`
跑自己的仓库时，同一天的日报与站点页面会被覆盖成你自己团队的内容——按日期幂等。）

## 开启邮件推送（以 QQ 邮箱为例）

1. QQ 邮箱 → 设置 → 账户 → 开启「IMAP/SMTP 服务」→ 生成**授权码**（16 位，**不是**登录密码）
2. 在项目根目录的 `.env` 里填两行（该文件已被 `.gitignore` 排除）：
   ```
   SMTP_USERNAME=你的邮箱@qq.com
   SMTP_PASSWORD=刚生成的授权码
   ```
3. `config.yaml` 的 `notify.email`：`enabled: true`，`host` 用 `smtp.qq.com`（163 用 `smtp.163.com`），
   `sender` 与 `SMTP_USERNAME` 保持一致，`recipients` 填收件人
4. 体检：`.\.venv\Scripts\python.exe main.py --config config.yaml --check`
   → 看到 `"event": "check_smtp", "ok": true` 就成了；缺哪个变量它会直接报出变量名
5. 正式发送（**去掉 `--dry-run`**）：
   `.\.venv\Scripts\python.exe main.py --config config.yaml --date 2026-09-26`

密钥解析优先级：**真实环境变量 > `.env`**；`.env` 会被程序自动加载（配置同目录与当前目录都认），
占位符解析为空值时视同缺失，由 `--check` 报出。飞书同理，见下一节。

### 邮件为什么和网页长得不完全一样（v2.6）

邮件正文和站点页面**内容是同一份**（同一个 `view` 渲染出来的），但**排版是两套**：

- 站点页面用带 `<style>` 与 CSS 变量的富样式——浏览器 100% 支持，观感最好；
- 邮件正文用邮件专用模板：表格布局 + 样式全部内联成字面量，不带 `<style>`、不带 `class`、不用 CSS 变量与 flex。

原因是邮件客户端对 CSS 的支持差异极大。之前的版本邮件直接复用网站页面，结果 QQ 邮箱的 PC 端会**丢弃所有依赖 CSS 变量的声明**：胶囊标签退化成一排黑字，页头那个白字「日」图标因为背景色被丢掉，白字落在白底上直接看不见了。改成内联样式后 PC 与手机基本一致，页头图标也用 `bgcolor` 属性做了双保险（即使客户端丢弃 CSS 背景，白字仍有底色）。

调试时可以直接打开 `output/daily-report-<日期>.email.html` 看邮件正文的实际产物（这个文件在 `output/` 下，不会进版本库）。

### 邮件主题怎么定（v2.4.1）

默认主题是 `[团队名] 日期 智能日报`。在 `notify.email` 里配一个前缀，主题就会带上它（各段用空格分隔）：

```yaml
notify:
  email:
    subject_prefix: 研一        # 收到的是「研一 王帅豪 2026-10-13 智能日报」
```

留空就回到默认格式。前缀里的多余空格会被自动归一，不会出现连续空格。这个前缀只影响**邮件主题**，邮件正文标题、飞书卡片标题、站点页面标题都不受它影响。

## 接入飞书群机器人（v1.2）

飞书在这里只是**推送通道**（数据源仍然只使用 GitHub）：日报生成后，把 Markdown 卡片推到一个飞书群。
用的是群里的「自定义机器人」，不需要建企业自建应用、不需要申请任何开放平台权限。

### 第 1 步：在飞书里拿到 Webhook 地址

1. 打开飞书，进入（或新建）你要接收日报的群
2. 群右上角 **设置 → 群机器人 → 添加机器人 → 自定义机器人**
3. 起个名字（如「智能日报」）→ 点 **添加**
4. 在「安全设置」里选一种（三选一，推荐第 1 种）：
   - **签名校验**：飞书给你一串密钥，**复制下来**（下面填到 `LARK_BOT_SECRET`）
   - **自定义关键词**：填 `日报`（本项目日报的标题、正文里都带"智能日报"，一定命中）
   - **IP 白名单**：只有在固定公网 IP 的服务器上跑才建议用
5. 复制 **Webhook 地址**，形如 `https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx-xxxx-xxxx`

### 第 2 步：填进 `.env` 与 `config.yaml`

`.env`（已被 `.gitignore` 排除，不会进版本库）：

```
LARK_BOT_WEBHOOK=粘贴第 1 步复制的 Webhook 地址
LARK_BOT_SECRET=第 1 步选「签名校验」时粘贴那串密钥；选关键词/白名单就留空
```

`config.yaml` 的 `notify.lark_bot`：

```yaml
notify:
  lark_bot:
    enabled: true                  # 确认自检通过后再改成 true
    webhook: ${LARK_BOT_WEBHOOK}
    secret: ${LARK_BOT_SECRET}     # 没启用签名校验就写 ""
```

### 第 3 步：自检（这一步不发日报、不发邮件）

```powershell
.\.venv\Scripts\python.exe main.py --config config.yaml --test-lark
```

- 成功：群里出现「智能日报 · 飞书机器人连通性自检」，命令行打印 `[飞书自检] 飞书机器人连通性正常…`
- 失败：命令行打印失败原因；`logs/daily-report.jsonl` 里有飞书返回体与提示
  （`19021` = 签名校验没过，检查 `LARK_BOT_SECRET`；`19024` = 关键词没命中，关键词填 `日报`）

### 第 4 步：正式推送

```powershell
# 先干跑看内容对不对（不推送）
.\.venv\Scripts\python.exe main.py --config config.yaml --dry-run --date 2026-09-26

# 去掉 --dry-run 才会真推送：飞书群收到卡片，邮件按 notify.email.enabled 决定发不发
.\.venv\Scripts\python.exe main.py --config config.yaml --date 2026-09-26
```

排错要点：

- 推送失败**不会**影响日报生成与站点渲染，失败只记日志（退出码不变），所以"群里没消息"时先看 `logs/daily-report.jsonl` 里的 `push_result`
- 机器人被移出群、Webhook 被重置后推送会失败，重跑一次 `--test-lark` 即可确认
- `--test-lark` 与 `--dry-run` 是两件不同的事：前者只验证飞书通道，后者只做"生成但不推送"

## 定时运行

### 演示/调试：启动一次，之后只刷新浏览器

```powershell
.\watch.ps1                      # 默认 config.yaml，每 5 分钟自动重跑一次
.\watch.ps1 -IntervalSeconds 60  # 想更快可以调到 60 秒（建议先配 GITHUB_TOKEN）
```

脚本会循环执行 `main.py --config <配置> --dry-run`，你只需要保持窗口开着，
在浏览器里按 F5 就能看到自己刚在 GitHub 上做的提交 / Issue / 评论。
它只是本地演示辅助工具，不属于 proposal.md 里"定时任务、不常驻服务"的流水线本身，
按 Ctrl+C 退出。

Windows 计划任务 / Linux Cron 每个工作日 18:00 执行：

```powershell
schtasks /Create /SC WEEKLY /D MON,TUE,WED,THU,FRI /TN "daily-report" /TR "D:\codex项目文档\作业二\.venv\Scripts\python.exe D:\codex项目文档\作业二\main.py" /ST 18:00
```

```cron
0 18 * * 1-5 cd /path/to/project && .venv/bin/python main.py
```

周末与 `report.holidays` 中列出的日期会被自动跳过（显式传 `--date/--since` 时按你的意图执行）。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

全部用例使用 Mock（`httpx.MockTransport`、假 SMTP），不访问真实网络、不发送真实通知；
覆盖正常、降级（单源失败）、空数据、数据源全部失败四种集成场景，以及分页、限流等待、
重试、字段完整性、敏感词过滤、站点链接、工作台载荷与渐进增强等验收点。

`generator/templates/workbench.js` 是内联进页面的浏览器脚本，仓库里没有 npm 工程，
因此用 `node --check generator/templates/workbench.js` 做语法校验，行为验证在浏览器里手测。

## 目录

- `specs/`：三份规范（需求 / 架构 / 任务）
- `collector/`：`github_commit.py`、`github_issue.py`、`github_discussion.py`
- `generator/`：`formatter.py`（日报编排）、`hours.py`（工时推导，v1.1）、`template.py`（Jinja2 模板）、`site.py`（静态站）、`templates/`（页面与邮件模板、样式、工作台脚本）
- `notifier/`：`email.py`（SMTP）、`lark_bot.py`（群机器人 Webhook）
- `shared/`：`config.py`、`logger.py`、`errors.py`、`http.py`、`filters.py`、`models.py`、`storage.py`
- `main.py`：编排入口
- `docs/`：静态日报站输出（GitHub Pages 目录）

## 推到 GitHub

`作业二` 目录本身不是独立仓库（父目录绑的是作业一的 Gitee 远端）。要发布到
`https://github.com/wsh-dotcommer/zuoye.git`，可以：

```powershell
cd D:\codex项目文档\作业二
git init
git add .
git commit -m "feat: SDD 复现智能日报生成器（含静态日报站）"
git branch -M main
git remote add origin https://github.com/wsh-dotcommer/zuoye.git
git push -u origin main
```

推送后按上面的三步开启 Pages 即可。`.gitignore` 已经排除了 `.venv/`、`config.yaml`、
`output/`、`logs/`、`data/` 与 `.env`，不会把凭据和本地产物传上去。
