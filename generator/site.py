"""静态日报站渲染（design.md §4.3，Task 6）。

接口契约：
    render_site(report, history, site_config) -> list[Path]
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from generator import formatter, template
from shared.models import DailyReport
from shared.storage import HistoryEntry


@dataclass(frozen=True)
class SiteConfig:
    directory: Path
    title: str


def render_site(
    report: DailyReport,
    history: list[HistoryEntry],
    site_config: SiteConfig,
) -> list[Path]:
    """渲染索引页、当日详情页与静态资源，返回写入的文件路径列表。"""

    directory = Path(site_config.directory)
    assets_dir = directory / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    style_path = assets_dir / "style.css"
    style_path.write_text(template.render_style(), encoding="utf-8")

    nojekyll_path = directory / ".nojekyll"
    nojekyll_path.write_text("", encoding="utf-8")

    detail_name = detail_file_name(report.date)
    detail_path = directory / detail_name
    view = formatter.build_view(report)
    detail_path.write_text(
        template.render_report_html(view, back_link=True),
        encoding="utf-8",
    )

    entries = _merge_entries(report, history, detail_name, directory)
    index_path = directory / "index.html"
    index_path.write_text(
        template.render_index_html(
            entries,
            site_title=site_config.title,
            team_name=report.team_name,
            generated_at=view["generated_at"],
        ),
        encoding="utf-8",
    )
    return [index_path, detail_path, style_path, nojekyll_path]


def detail_file_name(day) -> str:
    return f"daily-report-{day.isoformat()}.html"


def _merge_entries(
    report: DailyReport,
    history: list[HistoryEntry],
    detail_name: str,
    directory: Path,
) -> list[dict]:
    """合并历史与当日条目，剔除详情页缺失的日期（design.md §4.3）。"""

    merged: dict[str, HistoryEntry] = {entry.date.isoformat(): entry for entry in history}
    merged[report.date.isoformat()] = HistoryEntry(
        date=report.date,
        team_name=report.team_name,
        member_count=len(report.members),
        generated_at=report.generated_at,
        site_file=detail_name,
        markdown=report.markdown,
    )

    entries: list[dict] = []
    for key in sorted(merged, reverse=True):
        entry = merged[key]
        if entry.site_file != detail_name and not (Path(directory) / entry.site_file).exists():
            continue
        entries.append(
            {
                "date": entry.date.isoformat(),
                "site_file": entry.site_file,
                "member_count": entry.member_count,
                "generated_at": entry.generated_at.strftime("%Y-%m-%d %H:%M"),
            }
        )
    return entries
