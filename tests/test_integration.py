"""端到端集成测试（Task 10 验收）：正常 / 降级 / 空数据 / 全部失败 / 干跑。"""

from __future__ import annotations

from datetime import date
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

import main as main_module
from collector import feishu_message, feishu_task, github_commit, github_discussion, github_issue
from notifier import lark_bot
from shared.http import FeishuClient, TOKEN_PATH
from tests.conftest import (
    comment_item,
    commit_detail,
    commit_item,
    config_text,
    issue_item,
    patch_client,
)

DAY = "2026-09-18"

COMMITS = [
    commit_item("sha-a", "wsh-dotcommer", "hongdou@example.com", "2026-09-18T10:00:00Z"),
    commit_item("sha-b", "zhangsan", "zhangsan@example.com", "2026-09-18T11:00:00Z", "fix: 补充测试"),
]
ISSUES = [
    issue_item(
        1,
        "静态日报站上线",
        created_at="2026-09-18T01:00:00Z",
        updated_at="2026-09-18T05:00:00Z",
        closed_at="2026-09-18T05:00:00Z",
        state="closed",
        assignee="wsh-dotcommer",
    )
]
ISSUE_COMMENTS = [
    comment_item(
        "wsh-dotcommer",
        "feat: 索引页已经可以点击跳转",
        "2026-09-18T06:00:00Z",
        issue_url="https://api.github.com/repos/octo/demo/issues/1",
    )
]


class FakeApi:
    """最小可用的 GitHub API 模拟器（覆盖集成测试用到的全部端点）。"""

    def __init__(
        self,
        *,
        fail_all: bool = False,
        fail_issues: bool = False,
        fail_commits: bool = False,
        empty: bool = False,
    ) -> None:
        self.fail_all = fail_all
        self.fail_issues = fail_issues
        self.fail_commits = fail_commits
        self.empty = empty

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.fail_all:
            return httpx.Response(500, json={"message": "server error"})
        path = request.url.path
        if path == "/repos/octo/demo":
            return httpx.Response(200, json={"full_name": "octo/demo", "private": False, "default_branch": "main"})
        if self.fail_issues and (path.endswith("/issues") or path.endswith("/timeline")):
            return httpx.Response(500, json={"message": "issues down"})
        if self.fail_commits and "/commits" in path:
            return httpx.Response(500, json={"message": "commits down"})
        if path.endswith("/commits"):
            return httpx.Response(200, json=[] if self.empty else COMMITS)
        if "/commits/" in path:
            return httpx.Response(200, json=commit_detail(10, 2, 3))
        if path.endswith("/issues"):
            return httpx.Response(200, json=[] if self.empty else ISSUES)
        if path.endswith("/timeline"):
            return httpx.Response(200, json=[{"event": "closed", "created_at": "2026-09-18T05:00:00Z"}])
        if path.endswith("/issues/comments"):
            return httpx.Response(200, json=[] if self.empty else ISSUE_COMMENTS)
        if path.endswith("/pulls/comments"):
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"message": "not found"})


def _write_config(tmp_path: Path, extra: str = "", retry_times: int = 1) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(config_text(tmp_path, extra, retry_times=retry_times), encoding="utf-8")
    return path


def _write_config_with_lark(tmp_path: Path, *, retry_times: int = 1) -> Path:
    text = config_text(tmp_path, retry_times=retry_times).replace(
        "  lark_bot:\n    enabled: false",
        "  lark_bot:\n    enabled: true\n    webhook: https://open.feishu.cn/open-apis/bot/v2/hook/test",
    )
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _patch_collectors(monkeypatch: pytest.MonkeyPatch, api: FakeApi) -> None:
    for module in (github_commit, github_issue, github_discussion):
        patch_client(monkeypatch, module, api.handler, retry_times=1)


def _write_config_with_feishu(tmp_path: Path, *, credentials: str = "cli_demo") -> Path:
    text = config_text(tmp_path, retry_times=1).replace(
        "sources:\n  github:",
        "sources:\n  feishu:\n    enabled: true\n"
        f"    app_id: {credentials}\n    app_secret: app-secret\n"
        "    chats:\n      - id: oc_demo\n        name: 智能日报\n  github:",
    )
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _ms(hour: int) -> str:
    return str(int(datetime(2026, 9, 18, hour, 0, tzinfo=timezone.utc).timestamp() * 1000))


def _feishu_handler(*, ok: bool = True, messages: int = 3):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == TOKEN_PATH:
            if not ok:
                return httpx.Response(403, json={"code": 99991663, "msg": "no permission"})
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "t-demo"})
        if request.url.path == "/open-apis/im/v1/messages":
            items = [
                {
                    "message_id": f"om_{index}",
                    "msg_type": "text",
                    "create_time": _ms(1 + index),
                    "sender": {"id": f"ou_{index % 2}", "sender_type": "user"},
                    "body": {"content": "群聊机密内容"},
                }
                for index in range(messages)
            ]
            return httpx.Response(200, json={"code": 0, "data": {"items": items, "has_more": False}})
        return httpx.Response(404, json={"msg": "not found"})

    return handler


def _patch_feishu(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    def factory(config):
        feishu = config.sources.feishu
        return FeishuClient(
            feishu.app_id,
            feishu.app_secret,
            base_url=feishu.base_url,
            transport=httpx.MockTransport(handler),
            retry_times=1,
            retry_interval=0.0,
            sleep=lambda _seconds: None,
        )

    monkeypatch.setattr(feishu_message, "build_client", factory)
    # 任务采集器有自己的 build_client（要挂用户令牌提供者），这里一并替换
    monkeypatch.setattr(feishu_task, "build_client", factory)


def _write_config_with_feishu_tasks(tmp_path: Path) -> Path:
    """飞书任务同步开启、群消息关闭：只验证任务这条链路（v2.4）。"""

    text = config_text(tmp_path, retry_times=1).replace(
        "sources:\n  github:",
        "sources:\n  feishu:\n    enabled: false\n"
        "    app_id: cli_demo\n    app_secret: app-secret\n"
        "    tasks:\n      enabled: true\n      scope: all\n  github:",
    )
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _tasks_handler(*, ok: bool = True):
    """任务接口的 Mock：1 条已完成、1 条进行中、1 条未开始，外加一条权限错误分支。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == TOKEN_PATH:
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "t-demo"})
        if request.url.path == "/open-apis/task/v2/tasks":
            if not ok:
                return httpx.Response(
                    400,
                    json={
                        "code": 99991672,
                        "msg": "Access denied. One of the following scopes is required: "
                        "[task:task:read, task:task:write]",
                    },
                )
            items = [
                {"guid": "t-done", "summary": "静态日报站上线", "completed_at": "1790000000"},
                {"guid": "t-doing", "summary": "补集成测试", "completed_at": "0"},
                {
                    "guid": "t-todo",
                    "summary": "写验收文档",
                    "completed_at": "0",
                    "start": {"timestamp": "2524608000"},
                },
            ]
            return httpx.Response(
                200, json={"code": 0, "data": {"items": items, "has_more": False}}
            )
        return httpx.Response(404, json={"msg": "not found"})

    return handler


def test_full_pipeline_generates_report_and_site(tmp_path: Path, monkeypatch) -> None:
    api = FakeApi()
    _patch_collectors(monkeypatch, api)
    config_path = _write_config(tmp_path)

    exit_code = main_module.main(["--config", str(config_path), "--date", DAY, "--dry-run"])

    assert exit_code == 0
    markdown = (tmp_path / "output" / f"daily-report-{DAY}.md").read_text(encoding="utf-8")
    html = (tmp_path / "output" / f"daily-report-{DAY}.html").read_text(encoding="utf-8")
    index = (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")
    detail = (tmp_path / "docs" / f"daily-report-{DAY}.html").read_text(encoding="utf-8")

    assert "### 代码提交" in markdown
    assert "### 任务进展" in markdown
    assert "### 工时统计" in markdown
    assert "### 协作沟通" in markdown
    assert markdown.index("### 任务进展") < markdown.index("### 工时统计") < markdown.index("### 协作沟通")
    assert "- 工时：团队合计 1h · 人均 0.5h（按提交时间推导，非真实考勤）" in markdown
    assert "## 红豆（wsh-dotcommer）" in markdown
    assert "静态日报站上线：进行中 → 已完成" in markdown
    assert "feat: 索引页已经可以点击跳转" in markdown
    assert "<h3>代码提交</h3>" in html
    assert "<h3>工时统计</h3>" in html
    assert f'href="daily-report-{DAY}.html"' in index
    assert "← 返回日报列表" in detail
    assert "工时统计" in detail
    assert (tmp_path / "docs" / "assets" / "style.css").exists()
    assert (tmp_path / "docs" / ".nojekyll").exists()

    # v2.0：静态站内联日报工作台（表单/复制/本地草稿），详情页带复制与载入按钮
    assert 'id="workbench"' in index
    assert 'id="workbench-load"' in index
    assert f'<option value="{DAY}">' in index
    assert f'"date": "{DAY}"' in index
    assert 'id="report-copy"' in detail
    assert 'id="report-load"' in detail
    assert "### 代码提交" in detail.split('<script id="workbench-data"', 1)[1]

    storage_rows = (tmp_path / "data" / "reports.sqlite3")
    assert storage_rows.exists()
    log_lines = (tmp_path / "logs" / "test.jsonl").read_text(encoding="utf-8").splitlines()
    assert any('"event": "run_finished"' in line for line in log_lines)
    assert any('"source_collected"' in line for line in log_lines)


def test_degraded_source_is_marked_and_others_survive(tmp_path: Path, monkeypatch) -> None:
    api = FakeApi(fail_issues=True)
    _patch_collectors(monkeypatch, api)
    config_path = _write_config(tmp_path)

    exit_code = main_module.main(["--config", str(config_path), "--date", DAY, "--dry-run"])

    assert exit_code == 0
    markdown = (tmp_path / "output" / f"daily-report-{DAY}.md").read_text(encoding="utf-8")
    assert "数据获取失败" in markdown
    assert "feat: 索引页已经可以点击跳转" in markdown
    assert "### 代码提交" in markdown
    assert "### 工时统计" in markdown

    detail = (tmp_path / "docs" / f"daily-report-{DAY}.html").read_text(encoding="utf-8")
    assert 'id="report-copy"' in detail
    assert "数据获取失败" in detail


def test_empty_data_shows_placeholder(tmp_path: Path, monkeypatch) -> None:
    api = FakeApi(empty=True)
    _patch_collectors(monkeypatch, api)
    config_path = _write_config(tmp_path)

    exit_code = main_module.main(["--config", str(config_path), "--date", DAY, "--dry-run"])

    assert exit_code == 0
    markdown = (tmp_path / "output" / f"daily-report-{DAY}.md").read_text(encoding="utf-8")
    # v2.4：每位成员的空板块合并成一行，因此每人只剩一条合并占位
    assert markdown.count("- 今日无记录") == 2
    assert "- 今日无记录：代码提交、任务进展、协作沟通" in markdown
    assert "- 0h（今日无记录）" in markdown
    assert "- 工时：团队合计 0h · 人均 0h" in markdown

    index = (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")
    assert 'id="workbench"' in index
    assert "还没有本地草稿" in index


def test_hours_unavailable_when_commits_fail(tmp_path: Path, monkeypatch) -> None:
    """提交数据源失败时，工时板块必须显式标注不可用，其余板块正常（降级场景 v1.1）。"""

    api = FakeApi(fail_commits=True)
    _patch_collectors(monkeypatch, api)
    config_path = _write_config(tmp_path)

    exit_code = main_module.main(["--config", str(config_path), "--date", DAY, "--dry-run"])

    assert exit_code == 0
    markdown = (tmp_path / "output" / f"daily-report-{DAY}.md").read_text(encoding="utf-8")
    assert "工时数据不可用" in markdown
    assert "### 协作沟通" in markdown
    assert "feat: 索引页已经可以点击跳转" in markdown


def test_all_sources_failed_does_not_write_report(tmp_path: Path, monkeypatch) -> None:
    api = FakeApi(fail_all=True)
    _patch_collectors(monkeypatch, api)
    config_path = _write_config(tmp_path)

    exit_code = main_module.main(["--config", str(config_path), "--date", DAY, "--dry-run"])

    assert exit_code == 2
    assert not (tmp_path / "output").exists()
    assert not (tmp_path / "data").exists()
    log_lines = (tmp_path / "logs" / "test.jsonl").read_text(encoding="utf-8").splitlines()
    assert any('"event": "all_sources_failed"' in line for line in log_lines)


def test_dry_run_does_not_push(tmp_path: Path, monkeypatch) -> None:
    pushed: list[str] = []
    monkeypatch.setattr(lark_bot, "send", lambda *args, **kwargs: pushed.append("lark") or True)
    api = FakeApi()
    _patch_collectors(monkeypatch, api)
    config_path = _write_config_with_lark(tmp_path)

    exit_code = main_module.main(["--config", str(config_path), "--date", DAY, "--dry-run"])

    assert exit_code == 0
    assert pushed == []


def test_normal_run_pushes_to_lark_bot(tmp_path: Path, monkeypatch) -> None:
    pushed: list[str] = []
    monkeypatch.setattr(lark_bot, "send", lambda *args, **kwargs: pushed.append("lark") or True)
    api = FakeApi()
    _patch_collectors(monkeypatch, api)
    config_path = _write_config_with_lark(tmp_path)

    exit_code = main_module.main(["--config", str(config_path), "--date", DAY])

    assert exit_code == 0
    assert pushed == ["lark"]
    log_lines = (tmp_path / "logs" / "test.jsonl").read_text(encoding="utf-8").splitlines()
    assert any('"event": "push_result"' in line for line in log_lines)


def test_check_mode_passes_with_mock_api(tmp_path: Path, monkeypatch) -> None:
    api = FakeApi()
    for module in (github_commit, github_issue, github_discussion):
        patch_client(monkeypatch, module, api.handler)
    config_path = _write_config(tmp_path)

    exit_code = main_module.main(["--config", str(config_path), "--check"])

    assert exit_code == 0
    log_lines = (tmp_path / "logs" / "test.jsonl").read_text(encoding="utf-8").splitlines()
    assert any('"event": "check_passed"' in line for line in log_lines)


def test_explicit_date_bypasses_workday_skip(tmp_path: Path, monkeypatch) -> None:
    api = FakeApi()
    _patch_collectors(monkeypatch, api)
    path = tmp_path / "config.yaml"
    path.write_text(
        config_text(tmp_path).replace("skip_weekends: false", "skip_weekends: true"),
        encoding="utf-8",
    )

    exit_code = main_module.main(["--config", str(path), "--date", "2026-09-19"])

    # 显式指定日期时按用户意图执行，不做工作日跳过
    assert exit_code == 0
    assert (tmp_path / "output" / "daily-report-2026-09-19.md").exists()


def test_history_index_accumulates_across_days(tmp_path: Path, monkeypatch) -> None:
    api = FakeApi()
    _patch_collectors(monkeypatch, api)
    config_path = _write_config(tmp_path)

    assert main_module.main(["--config", str(config_path), "--date", DAY, "--dry-run"]) == 0
    second_day = "2026-09-21"
    assert main_module.main(["--config", str(config_path), "--date", second_day, "--dry-run"]) == 0

    index = (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")
    assert f'daily-report-{DAY}.html' in index
    assert f'daily-report-{second_day}.html' in index
    assert index.index(second_day) < index.index(DAY)
    assert date.fromisoformat(second_day) > date.fromisoformat(DAY)


def test_pipeline_includes_feishu_summary_without_content(tmp_path: Path, monkeypatch) -> None:
    api = FakeApi()
    _patch_collectors(monkeypatch, api)
    _patch_feishu(monkeypatch, _feishu_handler())
    config_path = _write_config_with_feishu(tmp_path)

    assert main_module.main(["--config", str(config_path), "--date", DAY, "--dry-run"]) == 0

    markdown = (tmp_path / "output" / f"daily-report-{DAY}.md").read_text(encoding="utf-8")
    assert "- 飞书群：智能日报 3 条 · 2 人发言" in markdown
    assert "飞书消息 3 条" in markdown  # 数据源徽章报的是消息总条数，不是群数量
    assert "群聊机密内容" not in markdown  # 正文绝不落盘


def test_pipeline_degrades_when_feishu_source_fails(tmp_path: Path, monkeypatch) -> None:
    api = FakeApi()
    _patch_collectors(monkeypatch, api)
    _patch_feishu(monkeypatch, _feishu_handler(ok=False))
    config_path = _write_config_with_feishu(tmp_path)

    assert main_module.main(["--config", str(config_path), "--date", DAY, "--dry-run"]) == 0

    markdown = (tmp_path / "output" / f"daily-report-{DAY}.md").read_text(encoding="utf-8")
    assert "飞书消息 数据获取失败" in markdown
    assert "### 代码提交" in markdown  # 其它源不受影响


def test_second_run_adds_comparison_trend_and_site_chart(tmp_path: Path, monkeypatch) -> None:
    api = FakeApi()
    _patch_collectors(monkeypatch, api)
    config_path = _write_config(tmp_path)

    assert main_module.main(["--config", str(config_path), "--date", "2026-09-16", "--dry-run"]) == 0
    assert main_module.main(["--config", str(config_path), "--date", "2026-09-17", "--dry-run"]) == 0
    assert main_module.main(["--config", str(config_path), "--date", DAY, "--dry-run"]) == 0

    markdown = (tmp_path / "output" / f"daily-report-{DAY}.md").read_text(encoding="utf-8")
    assert "- 对比上期（2026-09-17）：提交 +2 · 任务 +1 · 沟通 +1 · 工时 +1h" in markdown
    assert "- 近 3 期：提交 ▁▁█（2 条） · 工时 ▁▁█（1h）" in markdown

    index = (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")
    assert 'id="trend-title"' in index and "<svg" in index


def test_pipeline_includes_feishu_task_statuses(tmp_path: Path, monkeypatch) -> None:
    """v2.4：任务进展板块里出现飞书任务快照，三态齐全（集成）。"""

    api = FakeApi()
    _patch_collectors(monkeypatch, api)
    _patch_feishu(monkeypatch, _tasks_handler())
    config_path = _write_config_with_feishu_tasks(tmp_path)

    assert main_module.main(["--config", str(config_path), "--date", DAY, "--dry-run"]) == 0

    markdown = (tmp_path / "output" / f"daily-report-{DAY}.md").read_text(encoding="utf-8")
    assert "### 任务进展 · 飞书任务" in markdown
    assert "共 3 条：进行中 1 · 未开始 1 · 已完成 1" in markdown
    assert "- ● 进行中 · 补集成测试" in markdown
    assert "- ○ 未开始 · 写验收文档" in markdown
    assert "- ✓ 已完成 · 静态日报站上线" in markdown
    # 数据源徽章与标注都要认这个新源
    assert "飞书任务 1 条" not in markdown  # 徽章报的是本次采集条数（3），不是任务清单数
    assert "飞书任务 3 条" in markdown
    assert "数据来源：GitHub 仓库 octo/demo、飞书任务" in markdown

    detail = (tmp_path / "docs" / f"daily-report-{DAY}.html").read_text(encoding="utf-8")
    assert "<h4>任务进展 · 飞书任务" in detail
    assert '<p class="attribution">数据来源：GitHub 仓库 octo/demo、飞书任务' in detail


def test_pipeline_degrades_when_feishu_tasks_fail(tmp_path: Path, monkeypatch) -> None:
    api = FakeApi()
    _patch_collectors(monkeypatch, api)
    _patch_feishu(monkeypatch, _tasks_handler(ok=False))
    config_path = _write_config_with_feishu_tasks(tmp_path)

    assert main_module.main(["--config", str(config_path), "--date", DAY, "--dry-run"]) == 0

    markdown = (tmp_path / "output" / f"daily-report-{DAY}.md").read_text(encoding="utf-8")
    assert "飞书任务数据获取失败" in markdown
    assert "task:task:read" in markdown  # 提示要可执行，不能只丢原始错误码
    assert "### 代码提交" in markdown  # 其它源不受影响
    assert "- [#1]" in markdown


def test_attribution_can_be_disabled_by_config(tmp_path: Path, monkeypatch) -> None:
    api = FakeApi()
    _patch_collectors(monkeypatch, api)
    config_path = _write_config(tmp_path)
    text = config_path.read_text(encoding="utf-8").replace(
        "  skip_weekends: false",
        "  skip_weekends: false\n  attribution:\n    enabled: false",
    )
    config_path.write_text(text, encoding="utf-8")

    assert main_module.main(["--config", str(config_path), "--date", DAY, "--dry-run"]) == 0

    markdown = (tmp_path / "output" / f"daily-report-{DAY}.md").read_text(encoding="utf-8")
    index = (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")
    assert "数据来源" not in markdown
    assert '<p class="attribution">' not in index


def test_attribution_scope_is_configurable(tmp_path: Path, monkeypatch) -> None:
    api = FakeApi()
    _patch_collectors(monkeypatch, api)
    config_path = _write_config(tmp_path)
    text = config_path.read_text(encoding="utf-8").replace(
        "  skip_weekends: false",
        "  skip_weekends: false\n  attribution:\n    scope: 仅限甲方内部查阅",
    )
    config_path.write_text(text, encoding="utf-8")

    assert main_module.main(["--config", str(config_path), "--date", DAY, "--dry-run"]) == 0

    markdown = (tmp_path / "output" / f"daily-report-{DAY}.md").read_text(encoding="utf-8")
    assert "授权范围：仅限甲方内部查阅" in markdown
    assert "（北京时间）" in markdown


def test_check_passes_with_feishu_source(tmp_path: Path, monkeypatch) -> None:
    api = FakeApi()
    _patch_collectors(monkeypatch, api)
    _patch_feishu(monkeypatch, _feishu_handler())
    config_path = _write_config_with_feishu(tmp_path)

    assert main_module.main(["--config", str(config_path), "--check"]) == 0
