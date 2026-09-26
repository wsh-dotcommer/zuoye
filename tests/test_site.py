"""静态日报站渲染测试（Task 6 验收）。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from generator import formatter
from generator.site import SiteConfig, detail_file_name, render_site
from shared.config import MemberConfig
from shared.models import SOURCE_COMMIT, SOURCE_DISCUSSION, SOURCE_ISSUE, SourceStatus, DailyReport
from shared.storage import HistoryEntry, Storage

MEMBERS = [MemberConfig(name="红豆", github_username="wsh-dotcommer")]
STATUSES = [
    SourceStatus(name=SOURCE_COMMIT, ok=True, count=0),
    SourceStatus(name=SOURCE_ISSUE, ok=True, count=0),
    SourceStatus(name=SOURCE_DISCUSSION, ok=True, count=0),
]


def _report(day: date) -> DailyReport:
    report = formatter.generate(day, MEMBERS, [], [], [], STATUSES, "测试团队")
    report.generated_at = datetime(2026, 9, 18, 18, 0, tzinfo=timezone.utc)
    return report


def test_render_site_writes_expected_files(tmp_path: Path) -> None:
    report = _report(date(2026, 9, 18))
    storage = Storage(tmp_path / "data" / "reports.sqlite3")
    storage.save(report, detail_file_name(report.date))

    paths = render_site(
        report,
        storage.list_reports(),
        SiteConfig(directory=tmp_path / "docs", title="测试日报"),
    )

    names = {path.name for path in paths}
    assert names == {"index.html", "daily-report-2026-09-18.html", "style.css", ".nojekyll"}
    assert all(path.exists() for path in paths)

    index = (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")
    detail = (tmp_path / "docs" / "daily-report-2026-09-18.html").read_text(encoding="utf-8")
    assert 'href="daily-report-2026-09-18.html"' in index
    assert "2026-09-18" in index
    assert "1 名成员" in index
    assert "← 返回日报列表" in detail
    assert "### " not in detail  # HTML 页面不应残留 Markdown 标记


def test_index_skips_history_with_missing_detail_file(tmp_path: Path) -> None:
    yesterday = date(2026, 9, 17)
    report = _report(date(2026, 9, 18))
    history = [
        HistoryEntry(
            date=yesterday,
            team_name="测试团队",
            member_count=1,
            generated_at=datetime(2026, 9, 17, 18, 0, tzinfo=timezone.utc),
            site_file=detail_file_name(yesterday),
            markdown="# 昨天的日报",
        ),
        HistoryEntry(
            date=date(2026, 9, 16),
            team_name="测试团队",
            member_count=1,
            generated_at=datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc),
            site_file=detail_file_name(date(2026, 9, 16)),
            markdown="# 前天的日报",
        ),
    ]

    render_site(report, history, SiteConfig(directory=tmp_path / "docs", title="测试日报"))
    index = (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")

    assert 'href="daily-report-2026-09-18.html"' in index
    assert "2026-09-17" not in index  # 详情页缺失的历史被跳过
    assert "2026-09-16" not in index


def test_index_lists_history_when_detail_exists(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir(parents=True)
    yesterday = date(2026, 9, 17)
    (docs / detail_file_name(yesterday)).write_text("<html>昨天</html>", encoding="utf-8")

    report = _report(date(2026, 9, 18))
    history = [
        HistoryEntry(
            date=yesterday,
            team_name="测试团队",
            member_count=2,
            generated_at=datetime(2026, 9, 17, 18, 0, tzinfo=timezone.utc),
            site_file=detail_file_name(yesterday),
            markdown="# 昨天的日报",
        )
    ]

    render_site(report, history, SiteConfig(directory=docs, title="测试日报"))
    index = (docs / "index.html").read_text(encoding="utf-8")

    assert index.index("2026-09-18") < index.index("2026-09-17")  # 倒序
    assert "2 名成员" in index


def test_report_html_contains_no_back_link() -> None:
    report = _report(date(2026, 9, 18))
    assert "返回日报列表" not in report.html


def test_generated_at_is_formatted() -> None:
    report = _report(date(2026, 9, 18))
    assert report.generated_at.tzinfo is not None
    assert "- 生成时间：" in report.markdown
    # v1.1：MemberReport 增加 work_hours 字段，这里只比较身份字段
    assert (report.members[0].name, report.members[0].github_username) == ("红豆", "wsh-dotcommer")
    assert report.date - timedelta(days=1) == date(2026, 9, 17)
