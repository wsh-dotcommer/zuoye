# 智能日报生成器（SDD 复现 · 作业二）

依据《SDD 实战：规范驱动开发之道》第 4–6 章的贯穿项目，按
`proposal → design → tasks → code → verification` 走完一次规范驱动开发。
数据源**只使用 GitHub**：Commits 当"代码提交"、Issues 状态流转当"任务进展"、
PR/Issue 评论当"协作沟通"；飞书只作为推送通道。在书中范围之上增加了一项扩展：
**输出可发布的静态日报站**（GitHub Pages）。

规范文档在 [`specs/`](specs/) 下，是本次开发的唯一事实来源：

- `specs/proposal.md`：背景、范围（做什么/不做什么）、验收标准、术语
- `specs/design.md`：管道架构、模块职责、数据模型、接口契约、ADR、非功能性约束
- `specs/tasks.md`：10 个可验收任务与 7 阶段执行顺序

## 快速开始

```powershell
# 1. 安装依赖（Python 3.11+）
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

# 2. 生成自己的配置
Copy-Item config.yaml.example config.yaml    # 按需修改仓库与成员映射
Copy-Item .env.example .env                  # 按需填入凭据（.env 已被 gitignore）

# 3. 体检：配置、环境变量、GitHub / SMTP / 飞书 Webhook
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

## 产物

- `output/daily-report-<日期>.md` 与 `.html`：当日报表的两种形态
- `docs/index.html`：静态日报站索引页；`docs/daily-report-<日期>.html` 详情页
- `docs/assets/style.css`、`docs/.nojekyll`：站点静态资源
- `data/reports.sqlite3`：日报历史（按日期幂等覆盖）
- `logs/daily-report.jsonl`：JSON Lines 执行日志（开始时间、各数据源条数、推送结果、结束时间）

## 工时统计口径（v1.1）

日报里的"工时统计"由 **GitHub 提交时间推导**（不接考勤系统、不需要成员填报），算法叫会话法：

| 规则 | 默认值 | 配置项 |
| --- | --- | --- |
| 相邻提交间隔超过多久算新的工作段 | 60 分钟（等于阈值不算） | `hours.gap_minutes` |
| 每个工作段的收尾时长（只有一条提交的段按此计） | 0.5h | `hours.wrap_up_hours` |
| 结果四舍五入到的网格 | 0.5h | `hours.rounding_hours` |
| 单人单日上限 | 12h | `hours.daily_cap_hours` |
| 是否显示工时板块 | 显示 | `hours.enabled` |

计算方式：按自然日（`team.timezone`）把提交分到各天 → 切分工作段 → 每段时长 = 末次 − 首次 + 收尾 → 逐日封顶 → 按网格四舍五入 → 汇总。

几个必须知道的口径：

- **它是推导值，不是考勤值**。开会、写文档、读代码都不会被计入，日报头部固定标注"按提交时间推导，非真实考勤"。
- 成员当天没有提交 → `工时：0h（今日无记录）`；提交数据源失败 → `工时数据不可用（原因）`，两种情况含义完全不同。
- 推导是本地纯计算，不产生任何额外的 GitHub API 请求，也不影响限流预算。
- 想让数字更贴近真实节奏，就调 `hours.gap_minutes`（例如团队习惯一次提交间隔两小时，就调成 120）。

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
  仓库为空或当天没动静也走得通：日报会如实显示"今日无记录"，而不是报错。
- **别人的公开仓库**：直接换成对方的 `owner/name`。因为里面的作者不在你的成员表里，
  把 `sources.github.include_others` 打开，未映射作者会自动单独成段；
  机器人账号（`dependabot[bot]`、`github-actions[bot]` 等）默认被 `exclude_bots` 排除。
  公开大仓库请求量大，建议同时收紧 `max_commit_details` 与 `max_issue_timelines`。

仓库还没有内容时，可以用自带的演示配置先跑通"三个板块都有真实数据"的效果：

```powershell
Copy-Item config.demo.yaml.example config.demo.yaml
.\.venv\Scripts\python.exe main.py --config config.demo.yaml --dry-run `
  --since 2026-09-25T00:00:00 --until 2026-09-25T18:00:00
```

（演示配置采集的是 `openai/openai-python` 当天的真实公开数据；改用 `config.yaml`
跑自己的仓库时，同一天的日报与站点页面会被覆盖成你自己团队的内容——按日期幂等。）

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
重试、字段完整性、敏感词过滤、站点链接等验收点。

## 目录

- `specs/`：三份规范（需求 / 架构 / 任务）
- `collector/`：`github_commit.py`、`github_issue.py`、`github_discussion.py`
- `generator/`：`formatter.py`（日报编排）、`hours.py`（工时推导，v1.1）、`template.py`（Jinja2 模板）、`site.py`（静态站）
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
