"""邮件专用 HTML 渲染测试（v2.6 验收）。

核心不变量：邮件正文不能依赖任何"看客户端脸色"的 CSS 能力——没有 <style>、
没有 class、没有 CSS 变量、没有 flex/grid/clamp。否则 QQ 邮箱 PC 端会把
依赖 var() 的声明整条丢掉，白字落在白底上直接消失。
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from generator import formatter
from shared.config import MemberConfig
from shared.models import (
    SOURCE_COMMIT,
    SOURCE_DISCUSSION,
    SOURCE_FEISHU_TASK,
    SOURCE_ISSUE,
    CommitRecord,
    DataSourceRef,
    FeishuTaskRecord,
    MessageRecord,
    SourceStatus,
    TaskRecord,
)

MEMBERS = [MemberConfig(name="王帅豪", github_username="wsh-dotcommer")]
STATUSES_OK = [
    SourceStatus(name=SOURCE_COMMIT, ok=True, count=1),
    SourceStatus(name=SOURCE_ISSUE, ok=True, count=1),
    SourceStatus(name=SOURCE_DISCUSSION, ok=True, count=1),
]
REF = DataSourceRef(label="GitHub 仓库", full_name="octo/demo")

COMMITS = [
    CommitRecord(
        author="wsh-dotcommer",
        message="feat: 新增静态日报站",
        timestamp=datetime(2026, 9, 18, 10, 0, tzinfo=timezone.utc),
        repo="octo/demo",
        additions=120,
        deletions=3,
        files_changed=2,
        files=("a.py", "b.py"),
        sha="abc1234def",
        url="https://github.com/octo/demo/commit/abc1234def",
    )
]


def _full_report():
    """数据齐全的一期：覆盖正常板块、两行提交、飞书任务子小节。"""

    return formatter.generate(
        date(2026, 9, 18),
        MEMBERS,
        COMMITS,
        [
            TaskRecord(
                assignee="wsh-dotcommer",
                title="补齐集成测试",
                status_from="进行中",
                status_to="已完成",
                updated_at=datetime(2026, 9, 18, 11, 0, tzinfo=timezone.utc),
                number=7,
                url="https://github.com/octo/demo/issues/7",
            )
        ],
        [
            MessageRecord(
                sender="wsh-dotcommer",
                content="这里建议补测试",
                timestamp=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
                source="octo/demo PR #7",
                url="https://github.com/octo/demo/pull/7",
            )
        ],
        [*STATUSES_OK, SourceStatus(name=SOURCE_FEISHU_TASK, ok=True, count=1)],
        "王帅豪",
        feishu_tasks=[
            FeishuTaskRecord(guid="t1", summary="补集成测试", status="进行中"),
        ],
        source_refs=[REF],
        attribution_scope="仅限团队内部日报展示",
        public_base_url="https://example.com/reports/",
    )


def _sparse_report():
    """数据稀疏的一期：覆盖空板块合并 + 失败板块。"""

    statuses = [
        SourceStatus(name=SOURCE_COMMIT, ok=True, count=0),
        SourceStatus(name=SOURCE_ISSUE, ok=True, count=0),
        SourceStatus(name=SOURCE_DISCUSSION, ok=False, count=0, error="GitHub API 超时"),
    ]
    return formatter.generate(date(2026, 9, 18), MEMBERS, [], [], [], statuses, "王帅豪")


def test_email_html_avoids_client_hostile_constructs() -> None:
    html = _full_report().email_html

    assert "<style" not in html
    assert "class=" not in html
    assert "var(--" not in html
    assert "display:flex" not in html and "display: flex" not in html
    assert "display:grid" not in html and "display: grid" not in html
    assert "clamp(" not in html
    # 表格布局是邮件里的安全底座
    assert '<table role="presentation"' in html


def test_brand_mark_keeps_its_letter_visible() -> None:
    """页头那个「日」：bgcolor 属性 + 内联背景色双保险，白字永远不会掉在白底上。"""

    html = _full_report().email_html

    assert 'bgcolor="#176b5b"' in html
    assert "background-color:#176b5b" in html
    assert "color:#ffffff" in html
    assert ">日</td>" in html


def test_source_chips_use_literal_colors() -> None:
    html = _full_report().email_html

    assert "background-color:#e7f3ee" in html
    assert "color:#176b5b" in html
    assert "border:1px solid #cfe3d9" in html
    assert "代码提交 1 条" in html

    failed = _sparse_report().email_html
    assert "background-color:#fff1ef" in failed
    assert "color:#a53939" in failed


def test_commit_entries_render_as_two_rows() -> None:
    html = _full_report().email_html

    assert "<div>octo/demo feat: 新增静态日报站</div>" in html
    assert '<div style="color:#697770;font-size:12.5px;">' in html
    assert "abc1234" in html


def test_links_carry_inline_color() -> None:
    html = _full_report().email_html

    assert 'style="color:#176b5b;text-decoration:underline;"' in html
    assert 'href="https://github.com/octo/demo/commit/abc1234def"' in html
    assert "[abc1234]" not in html  # Markdown 标记不该残留


def test_section_states_render_like_detail_page() -> None:
    html = _sparse_report().email_html

    # 两个以上空板块合并成一行
    assert "今日无记录：代码提交、任务进展" in html
    # 失败板块带自己的配色
    assert "数据获取失败（GitHub API 超时）" in html
    assert "background-color:#fff1ef" in html


def test_feishu_task_subsection_renders() -> None:
    html = _full_report().email_html

    assert "任务进展 · 飞书任务" in html
    assert "共 1 条" in html
    assert "● 进行中 · 补集成测试" in html


def test_management_summary_and_online_button_are_inline_safe() -> None:
    html = _full_report().email_html

    assert "管理摘要" in html
    assert "今日概览" in html and "需要关注" in html and "下一步" in html
    assert "https://example.com/reports/daily-report-2026-09-18.html" in html
    assert "查看当天完整日报" in html
    assert 'bgcolor="#176b5b"' in html
    assert "display:inline-block" in html


def test_online_button_is_absent_when_public_url_is_empty() -> None:
    report = formatter.generate(
        date(2026, 9, 18),
        MEMBERS,
        COMMITS,
        [],
        [],
        STATUSES_OK,
        "王帅豪",
    )

    assert "查看当天完整日报" not in report.email_html


def test_attribution_and_footer_close_the_email() -> None:
    html = _full_report().email_html

    assert "数据来源：GitHub 仓库 octo/demo ｜ 采集时间：" in html
    assert html.rstrip().endswith("</html>")
    assert html.index("由智能日报生成器生成") < html.index("数据来源：GitHub 仓库")


def test_email_html_stays_script_free() -> None:
    html = _full_report().email_html

    assert "<script" not in html
    assert "复制 Markdown" not in html
    assert "载入到工作台" not in html


def test_site_html_keeps_rich_style_and_email_does_not() -> None:
    """站点继续用带变量的富样式；邮件走自己的模板，两者互不影响。"""

    report = _full_report()

    assert "<style" in report.html and "var(--" in report.html
    assert "<style" not in report.email_html
    assert report.email_html != report.html
