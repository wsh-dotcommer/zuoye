"""HTML 模板渲染（design.md §2、§4.3，Task 6；工作台见 §4.3 与 ADR-008，v2.0）。

模板随包分发在 generator/templates/ 下，站点页、邮件正文与索引页共用一套基础模板。
站点页额外内联「日报工作台」脚本与 JSON 载荷；邮件正文保持无脚本（`interactive=False`）。
"""

from __future__ import annotations

import json
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


def render_report_html(
    view: dict,
    *,
    back_link: bool = False,
    markdown: str | None = None,
    interactive: bool = False,
) -> str:
    """渲染单份日报（邮件正文与站点详情页共用）。

    `interactive=True` 时输出工作台脚本与本期 Markdown 载荷（站点详情页）；
    缺省 `interactive=False` 让邮件正文保持无脚本、无按钮。
    """

    return _env.get_template("report.html.j2").render(
        view=view,
        style=render_style(),
        page_title=view["title"],
        generated_at=view["generated_at"],
        back_link=back_link,
        interactive=interactive,
        workbench_data=render_workbench_data(view, markdown),
        workbench_js=render_workbench_js() if interactive else "",
    )


def render_index_html(
    entries: Sequence[dict],
    *,
    site_title: str,
    team_name: str,
    generated_at: str,
    interactive: bool = True,
) -> str:
    """渲染静态站索引页（含工作台与历史载荷）。"""

    return _env.get_template("index.html.j2").render(
        entries=entries,
        site_title=site_title,
        team_name=team_name,
        page_title=site_title,
        style=render_style(),
        generated_at=generated_at,
        interactive=interactive,
        workbench_data=render_workbench_data(entries),
        workbench_js=render_workbench_js() if interactive else "",
    )


def render_workbench_js() -> str:
    """读取工作台脚本（内联进站点页面，不单独产出文件）。"""

    return (_TEMPLATE_DIR / "workbench.js").read_text(encoding="utf-8")


def render_workbench_data(view_or_entries, markdown: str | None = None) -> str:
    """把日报正文序列化成页面内联 JSON 载荷（design.md §4.3）。

    `<`、`>`、`&` 统一转成 JSON 的 `\\uXXXX` 形式，避免正文里的
    `</script>` 之类的序列提前闭合脚本标签。
    """

    if isinstance(view_or_entries, dict):
        entries: Sequence[dict] = [
            {"date": view_or_entries["date"], "markdown": markdown or ""}
        ]
    else:
        entries = view_or_entries

    reports = [
        {
            "date": str(entry["date"]),
            "markdown": str(entry.get("markdown") or ""),
        }
        for entry in entries
    ]
    payload = json.dumps({"reports": reports}, ensure_ascii=False)
    for char, escaped in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026")):
        payload = payload.replace(char, escaped)
    return payload


def render_style() -> str:
    """读取站点/邮件共用的 CSS。"""

    return (_TEMPLATE_DIR / "style.css").read_text(encoding="utf-8")
