"""日报工作台测试（design.md §4.3、ADR-008，Task 13/14 验收，v2.0）。

工作台的交互逻辑跑在浏览器里，这里只验证「服务端产出的页面契约」：
载荷、脚本内联、按钮、渐进增强与关闭开关。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from generator import formatter, template
from generator.site import SiteConfig, detail_file_name, render_site
from shared.config import MemberConfig
from shared.models import (
    SOURCE_COMMIT,
    SOURCE_DISCUSSION,
    SOURCE_ISSUE,
    DailyReport,
    SourceStatus,
)
from shared.storage import HistoryEntry, Storage

MEMBERS = [MemberConfig(name="红豆", github_username="wsh-dotcommer")]
STATUSES = [
    SourceStatus(name=SOURCE_COMMIT, ok=True, count=0),
    SourceStatus(name=SOURCE_ISSUE, ok=True, count=0),
    SourceStatus(name=SOURCE_DISCUSSION, ok=True, count=0),
]
INJECTION = "# 智能日报 · 2026-09-18\n\n### 代码提交\n- feat: </script><script>alert(1)</script> 补测试\n"


def _report(day: date = date(2026, 9, 18), markdown: str | None = None) -> DailyReport:
    report = formatter.generate(day, MEMBERS, [], [], [], STATUSES, "测试团队")
    report.generated_at = datetime(2026, 9, 18, 18, 0, tzinfo=timezone.utc)
    if markdown is not None:
        report.markdown = markdown
    return report


def _history(day: date, markdown: str = "# 历史日报\n\n### 代码提交\n- feat: 昨天的活") -> HistoryEntry:
    return HistoryEntry(
        date=day,
        team_name="测试团队",
        member_count=2,
        generated_at=datetime(day.year, day.month, day.day, 18, 0, tzinfo=timezone.utc),
        site_file=detail_file_name(day),
        markdown=markdown,
    )


def _render(
    tmp_path: Path,
    *,
    workbench: bool = True,
    history: list[HistoryEntry] | None = None,
    report: DailyReport | None = None,
) -> tuple[str, str, Path]:
    docs = tmp_path / "docs"
    report = report or _report()
    history = history or []
    docs.mkdir(parents=True, exist_ok=True)
    for entry in history:
        (docs / entry.site_file).write_text("<html>历史</html>", encoding="utf-8")

    render_site(
        report,
        history,
        SiteConfig(directory=docs, title="测试日报", workbench=workbench),
    )
    index = (docs / "index.html").read_text(encoding="utf-8")
    detail = (docs / detail_file_name(report.date)).read_text(encoding="utf-8")
    return index, detail, docs


def test_index_renders_workbench_ui(tmp_path: Path) -> None:
    index, _, _ = _render(tmp_path)

    for element_id in (
        'id="workbench"',
        'id="workbench-date"',
        'id="workbench-today"',
        'id="workbench-tomorrow"',
        'id="workbench-blockers"',
        'id="workbench-load"',
        'id="workbench-generate"',
        'id="workbench-sample"',
        'id="workbench-output"',
        'id="workbench-copy"',
        'id="draft-list"',
        'id="draft-empty"',
        'id="draft-clear"',
        'id="toast"',
    ):
        assert element_id in index, element_id
    assert "日报工作台" in index
    assert "本地整理" in index


def test_index_payload_lists_every_history_date(tmp_path: Path) -> None:
    history = [_history(date(2026, 9, 17)), _history(date(2026, 9, 16))]
    index, _, _ = _render(tmp_path, history=history)

    payload = index.split('<script id="workbench-data"', 1)[1]
    assert '"2026-09-18"' in payload
    assert '"2026-09-17"' in payload
    assert '"2026-09-16"' in payload
    assert "昨天的活" in payload
    # 下拉里也要能选到历史日期，保证无脚本时仍能看到有哪些期
    assert '<option value="2026-09-17">' in index


def test_payload_escapes_script_injection(tmp_path: Path) -> None:
    report = _report(markdown=INJECTION)
    index, detail, _ = _render(
        tmp_path,
        history=[_history(date(2026, 9, 17), markdown=INJECTION)],
        report=report,
    )

    for page in (index, detail):
        assert "</script><script>alert(1)</script>" not in page
        assert "\\u003c/script\\u003e" in page
    assert "<script>alert(1)</script>" not in detail


def test_detail_page_has_actions_and_payload(tmp_path: Path) -> None:
    _, detail, _ = _render(tmp_path)

    assert 'id="report-copy"' in detail
    assert 'id="report-load"' in detail
    assert "复制 Markdown" in detail
    assert "载入到工作台" in detail
    payload = detail.split('<script id="workbench-data"', 1)[1]
    assert '"2026-09-18"' in payload
    assert "### 代码提交" in payload.replace("\\u003c", "<")


def test_detail_page_without_workbench_has_no_actions(tmp_path: Path) -> None:
    _, detail, _ = _render(tmp_path, workbench=False)

    assert "<script" not in detail
    assert "复制 Markdown" not in detail
    assert "载入到工作台" not in detail
    assert "← 返回日报列表" in detail


def test_workbench_can_be_disabled(tmp_path: Path) -> None:
    index, _, _ = _render(tmp_path, workbench=False, history=[_history(date(2026, 9, 17))])

    assert "<script" not in index
    assert 'id="workbench"' not in index
    assert 'id="workbench-date"' not in index
    assert "从自动日报载入" not in index
    # 关闭后索引页仍是完整的只读站
    assert 'href="daily-report-2026-09-17.html"' in index
    assert "2 名成员" in index


def test_email_html_stays_script_free() -> None:
    report = _report()

    assert "<script" not in report.html
    assert "复制 Markdown" not in report.html
    assert "### 代码提交" not in report.html


def test_workbench_js_contract() -> None:
    js = template.render_workbench_js()

    assert "daily-report-workbench:history:v1" in js
    assert "daily-report-workbench:pending:v1" in js
    assert "HISTORY_LIMIT = 50" in js
    assert "navigator.clipboard" in js
    assert "execCommand" in js
    assert "innerHTML" not in js
    assert "</script" not in js
    assert "{{" not in js


def test_workbench_storage_available_flag(tmp_path: Path) -> None:
    """localStorage 不可用时页面仍可渲染，只提示草稿只在本次会话内有效。"""

    index, _, _ = _render(tmp_path)

    assert "当前浏览器不允许本地存储" in index


def test_index_without_history_still_renders_workbench(tmp_path: Path) -> None:
    index, _, _ = _render(tmp_path)

    assert 'id="workbench"' in index
    assert "还没有本地草稿" in index
    assert '<option value="">选择一期自动日报…</option>' in index


def test_site_still_writes_four_files(tmp_path: Path) -> None:
    """工作台内联进页面，产物清单不新增文件（design.md §4.3）。"""

    docs = tmp_path / "docs"
    storage = Storage(tmp_path / "data" / "reports.sqlite3")
    report = _report()
    storage.save(report, detail_file_name(report.date))

    paths = render_site(
        report,
        storage.list_reports(),
        SiteConfig(directory=docs, title="测试日报"),
    )

    assert {path.name for path in paths} == {
        "index.html",
        "daily-report-2026-09-18.html",
        "style.css",
        ".nojekyll",
    }
