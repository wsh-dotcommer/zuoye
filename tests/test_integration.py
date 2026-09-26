"""端到端集成测试（Task 10 验收）：正常 / 降级 / 空数据 / 全部失败 / 干跑。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import pytest

import main as main_module
from collector import github_commit, github_discussion, github_issue
from notifier import lark_bot
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


def test_empty_data_shows_placeholder(tmp_path: Path, monkeypatch) -> None:
    api = FakeApi(empty=True)
    _patch_collectors(monkeypatch, api)
    config_path = _write_config(tmp_path)

    exit_code = main_module.main(["--config", str(config_path), "--date", DAY, "--dry-run"])

    assert exit_code == 0
    markdown = (tmp_path / "output" / f"daily-report-{DAY}.md").read_text(encoding="utf-8")
    assert markdown.count("- 今日无记录") == 6  # 2 名成员 × 3 个板块
    assert "- 0h（今日无记录）" in markdown
    assert "- 工时：团队合计 0h · 人均 0h" in markdown


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
