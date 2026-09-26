"""GitHub 讨论采集测试（Task 5 验收）。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import httpx

from collector import github_discussion
from tests.conftest import comment_item, json_response, patch_client

START = datetime(2026, 9, 17, 16, 0, tzinfo=timezone.utc)
END = datetime(2026, 9, 18, 16, 0, tzinfo=timezone.utc)

ISSUE_COMMENTS = [
    comment_item("wsh-dotcommer", "feat: 这个方案我同意", "2026-09-18T03:00:00Z"),
    comment_item("zhangsan", "无关的闲聊内容", "2026-09-18T04:00:00Z"),
    comment_item("zhangsan", "绩效相关讨论", "2026-09-18T05:00:00Z"),
    comment_item("wsh-dotcommer", "fix: 窗口外的评论", "2026-09-19T03:00:00Z"),
]

PULL_COMMENTS = [
    comment_item("zhangsan", "fix: 建议补一个单元测试", "2026-09-18T06:00:00Z"),
]


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/issues/comments"):
        return json_response(ISSUE_COMMENTS)
    if path.endswith("/pulls/comments"):
        return json_response(PULL_COMMENTS)
    return httpx.Response(404, json={"message": "not found"})


def test_collect_filters_keywords_and_sensitive_words(config, monkeypatch) -> None:
    patch_client(monkeypatch, github_discussion, _handler)

    records = github_discussion.collect(config, START, END)

    contents = [record.content for record in records]
    assert contents == ["feat: 这个方案我同意", "fix: 建议补一个单元测试"]
    assert all(record.sender and record.source and record.timestamp for record in records)
    assert {record.source for record in records} == {"octo/demo #12", "octo/demo PR #7"}


def test_collect_returns_everything_when_keywords_empty(config, monkeypatch) -> None:
    patch_client(monkeypatch, github_discussion, _handler)
    without_keywords = replace(
        config,
        sources=replace(config.sources, github=replace(config.sources.github, keywords=())),
    )

    records = github_discussion.collect(without_keywords, START, END)

    # 关键词白名单为空时保留全部非敏感内容（窗口外的仍然剔除）
    assert len(records) == 3
    assert all("绩效" not in record.content for record in records)


def test_passes_filters_helper(config) -> None:
    github = config.sources.github
    assert github_discussion.passes_filters("feat: 新增模块", github) is True
    assert github_discussion.passes_filters("普通讨论", github) is False
    assert github_discussion.passes_filters("feat 但涉及薪资", github) is False


def test_bot_comments_are_excluded_by_default(config, monkeypatch) -> None:
    bot_comment = comment_item("github-actions[bot]", "feat: 机器人报告", "2026-09-18T07:00:00Z")
    typed_bot = comment_item("some-reviewer", "feat: 机器人评审", "2026-09-18T08:00:00Z")
    typed_bot["user"]["type"] = "Bot"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/issues/comments"):
            return json_response([*ISSUE_COMMENTS, bot_comment, typed_bot])
        return json_response([])

    patch_client(monkeypatch, github_discussion, handler)

    records = github_discussion.collect(config, START, END)

    # 关键词过滤后只剩一条人工评论；两条机器人评论被排除
    assert {record.sender for record in records} == {"wsh-dotcommer"}
    assert all("机器人" not in record.content for record in records)


def test_bot_comments_can_be_kept_when_disabled(config, monkeypatch) -> None:
    bot_comment = comment_item("dependabot[bot]", "fix: 依赖升级", "2026-09-18T07:00:00Z")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/issues/comments"):
            return json_response([bot_comment])
        return json_response([])

    relaxed = replace(
        config,
        sources=replace(config.sources, github=replace(config.sources.github, exclude_bots=False)),
    )
    patch_client(monkeypatch, github_discussion, handler)

    records = github_discussion.collect(relaxed, START, END)

    assert [record.sender for record in records] == ["dependabot[bot]"]
