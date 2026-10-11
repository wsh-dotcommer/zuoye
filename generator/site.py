"""静态日报站渲染（design.md §4.3，Task 6；工作台 v2.0）。

接口契约：
    render_site(report, history, site_config) -> list[Path]

v2.0 起站点页面可选内联「日报工作台」：产物仍是
`index.html`、`daily-report-<date>.html`、`assets/style.css`、`.nojekyll` 四个文件，
脚本与 JSON 载荷内联在页面里，不新增文件、不新增后端。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from generator import formatter, template
from shared.models import DailyReport
from shared.storage import HistoryEntry

# 索引页趋势区块（v2.3）：内联 SVG，不引图表库、不发请求
TREND_LIMIT = 7
TREND_MIN_POINTS = 2
TREND_BAR_WIDTH = 16
TREND_GAP = 12
TREND_HEIGHT = 96
TREND_TOP = 14
TREND_BOTTOM = 22


@dataclass(frozen=True)
class SiteConfig:
    directory: Path
    title: str
    workbench: bool = True


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
        template.render_report_html(
            view,
            back_link=True,
            markdown=report.markdown,
            interactive=site_config.workbench,
        ),
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
            interactive=site_config.workbench,
            trend=build_trend(history),
        ),
        encoding="utf-8",
    )
    return [index_path, detail_path, style_path, nojekyll_path]


def detail_file_name(day) -> str:
    return f"daily-report-{day.isoformat()}.html"


def build_trend(history: list[HistoryEntry], *, limit: int = TREND_LIMIT) -> dict | None:
    """近 N 期趋势（v2.3）：只取有结构化统计的那几期。

    少于两期（单点看不出趋势）或全为 0 时返回 None，索引页就不渲染该区块。
    """

    entries = [entry for entry in history if entry.to_stats() is not None]
    entries.sort(key=lambda item: item.date)
    entries = entries[-limit:]
    if len(entries) < TREND_MIN_POINTS:
        return None
    series = [entry.to_stats() for entry in entries]
    commits = [item.commit_count for item in series]
    hours = [item.total_hours for item in series]
    if not any(commits) and not any(hours):
        return None
    labels = [item.date.strftime("%m-%d") for item in series]
    return {
        "count": len(series),
        "commits": _chart(commits, labels),
        "hours": _chart(hours, labels),
    }


def _chart(values: list[float], labels: list[str]) -> dict:
    """把一串数值算成 SVG 柱子的坐标（几何在这里算好，模板只负责画）。"""

    peak = max(values) if values else 0
    plot = TREND_HEIGHT - TREND_TOP - TREND_BOTTOM
    base = TREND_HEIGHT - TREND_BOTTOM
    bars: list[dict] = []
    for index, (value, label) in enumerate(zip(values, labels)):
        height = 0 if value <= 0 or peak <= 0 else max(2, round(value / peak * plot))
        x = TREND_GAP + index * (TREND_BAR_WIDTH + TREND_GAP)
        bars.append(
            {
                "x": x,
                "y": base - height,
                "width": TREND_BAR_WIDTH,
                "height": height,
                "label_x": x + TREND_BAR_WIDTH / 2,
                "value_y": base - height - 4,
                "label_y": TREND_HEIGHT - 6,
                "label": label,
                "value": _format_value(value),
            }
        )
    return {
        "width": TREND_GAP + len(values) * (TREND_BAR_WIDTH + TREND_GAP),
        "height": TREND_HEIGHT,
        "bars": bars,
    }


def _format_value(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


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
                "markdown": entry.markdown,
            }
        )
    return entries
