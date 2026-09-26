"""HTML 模板渲染（design.md §2、§4.3，Task 6）。

模板随包分发在 generator/templates/ 下，站点页、邮件正文与索引页共用一套基础模板。
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(enabled_extensions=("html", "j2"), default=True),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_report_html(view: dict, *, back_link: bool = False) -> str:
    """渲染单份日报（邮件正文与站点详情页共用）。"""

    return _env.get_template("report.html.j2").render(
        view=view,
        style=render_style(),
        page_title=view["title"],
        generated_at=view["generated_at"],
        back_link=back_link,
    )


def render_index_html(
    entries: Sequence[dict],
    *,
    site_title: str,
    team_name: str,
    generated_at: str,
) -> str:
    """渲染静态站索引页。"""

    return _env.get_template("index.html.j2").render(
        entries=entries,
        site_title=site_title,
        team_name=team_name,
        page_title=site_title,
        style=render_style(),
        generated_at=generated_at,
    )


def render_style() -> str:
    """读取站点/邮件共用的 CSS。"""

    return (_TEMPLATE_DIR / "style.css").read_text(encoding="utf-8")
