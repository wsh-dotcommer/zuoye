"""数据来源标注合规性测试（v2.4 验收）。

对外的每一份产物——邮件正文（Markdown + HTML）、飞书卡片、站点详情页、
站点索引页——末尾都必须出现同一行三要素标注，且三端内容逐字一致。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from generator import formatter
from generator.site import SiteConfig, detail_file_name, render_site
from generator import template
from notifier import lark_bot
from shared.config import MemberConfig
from shared.models import (
    SOURCE_COMMIT,
    SOURCE_DISCUSSION,
    SOURCE_ISSUE,
    DailyReport,
    DataSourceRef,
    MemberReport,
    SourceStatus,
)

MEMBERS = [MemberConfig(name="红豆", github_username="wsh-dotcommer")]
STATUSES = [
    SourceStatus(name=SOURCE_COMMIT, ok=True, count=1),
    SourceStatus(name=SOURCE_ISSUE, ok=True, count=1),
    SourceStatus(name=SOURCE_DISCUSSION, ok=True, count=1),
]
REFS = (
    DataSourceRef(label="GitHub 仓库", full_name="octo/demo"),
    DataSourceRef(label="飞书群", full_name="智能日报"),
)
SCOPE = "仅限团队内部日报展示"


def _report(*, source_refs=REFS, markdown: str | None = None) -> DailyReport:
    report = formatter.generate(
        date(2026, 9, 18),
        MEMBERS,
        [],
        [],
        [],
        STATUSES,
        "测试团队",
        source_refs=source_refs,
        attribution_scope=SCOPE,
    )
    report.generated_at = datetime(2026, 9, 18, 18, 0, tzinfo=timezone.utc)
    # 固定生成时间后重算标注，产物才是可断言的（否则会写进"现在"）
    report.attribution = formatter.build_attribution(
        generated_at=report.generated_at,
        source_refs=source_refs,
        scope=SCOPE,
        timezone_name="Asia/Shanghai",
    )
    view = formatter.build_view(report)
    report.markdown = markdown if markdown is not None else formatter.render_markdown(view)
    report.html = template.render_report_html(view)
    return report


def test_attribution_contains_three_elements_in_order() -> None:
    attribution = _report().attribution

    assert attribution == (
        "数据来源：GitHub 仓库 octo/demo、飞书群 智能日报"
        " ｜ 采集时间：2026-09-18 18:00（北京时间）"
        f" ｜ 授权范围：{SCOPE}"
    )
    assert attribution.index("数据来源：") < attribution.index("采集时间：") < attribution.index("授权范围：")


def test_markdown_ends_with_attribution() -> None:
    markdown = _report().markdown

    assert markdown.rstrip().endswith(_report().attribution)


def test_html_footer_carries_attribution() -> None:
    assert '<p class="attribution">数据来源：GitHub 仓库 octo/demo' in _report().html


def test_lark_card_carries_attribution() -> None:
    report = _report()
    payload = lark_bot.build_payload(report)
    content = payload["card"]["elements"][0]["text"]["content"]

    assert report.attribution in content


def test_lark_card_keeps_attribution_even_when_truncated() -> None:
    """标注是合规要求：正文超长被截断时，标注行必须仍然在卡片末尾。"""

    report = _report()
    report.markdown = "# 很长的日报\n\n" + ("填充内容 " * 1200) + "\n\n" + report.attribution

    payload = lark_bot.build_payload(report)
    content = payload["card"]["elements"][0]["text"]["content"]

    assert "已截断" in content
    assert content.rstrip().endswith(report.attribution)
    assert len(content) <= lark_bot.MAX_MARKDOWN_LENGTH + 40


def test_site_pages_carry_attribution(tmp_path: Path) -> None:
    report = _report()
    docs = tmp_path / "docs"

    render_site(report, [], SiteConfig(directory=docs, title="测试日报", workbench=False))

    detail = (docs / detail_file_name(report.date)).read_text(encoding="utf-8")
    index = (docs / "index.html").read_text(encoding="utf-8")
    assert report.attribution in detail
    assert report.attribution in index


def test_attribution_can_be_disabled() -> None:
    """关闭开关（不传任何数据源）时，三端产物回到不含标注的形态。"""

    report = _report(source_refs=())

    assert report.attribution == ""
    assert "数据来源" not in report.markdown
    assert '<p class="attribution">' not in report.html


def test_attribution_falls_back_to_default_scope() -> None:
    report = formatter.generate(
        date(2026, 9, 18),
        MEMBERS,
        [],
        [],
        [],
        STATUSES,
        "测试团队",
        source_refs=REFS,
    )

    assert f"授权范围：{SCOPE}" in report.attribution


def test_source_ref_without_full_name_renders_label_only() -> None:
    assert DataSourceRef(label="飞书任务").render() == "飞书任务"


def test_report_model_keeps_attribution_field() -> None:
    report = DailyReport(
        date=date(2026, 9, 18),
        team_name="测试团队",
        members=[MemberReport(name="红豆", github_username="wsh-dotcommer")],
        generated_at=datetime(2026, 9, 18, 18, 0, tzinfo=timezone.utc),
        attribution="数据来源：X ｜ 采集时间：Y ｜ 授权范围：Z",
    )

    assert report.attribution.startswith("数据来源：X")
