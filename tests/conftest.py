"""测试夹具与 Mock 工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import httpx
import pytest

from shared.config import Config, load_config
from shared.http import GitHubClient
from shared.logger import build_logger

Handler = Callable[[httpx.Request], httpx.Response]


def config_text(tmp_path: Path, extra: str = "", *, retry_times: int = 3) -> str:
    root = tmp_path.as_posix()
    return f"""
team:
  name: 测试团队
  leader_email: leader@example.com
  timezone: Asia/Shanghai
repos:
  - owner: octo
    name: demo
members:
  - name: 红豆
    github_username: wsh-dotcommer
    github_emails: [hongdou@example.com]
  - name: 张三
    github_username: zhangsan
sources:
  github:
    token: ${{GITHUB_TOKEN}}
    keywords: [feat, fix]
    sensitive_keywords: [薪资, 绩效]
    retry_times: {retry_times}
    retry_interval_seconds: 0
report:
  output_dir: {root}/output
  site_dir: {root}/docs
  site_title: 测试日报
  storage_path: {root}/data/reports.sqlite3
  log_path: {root}/logs/test.jsonl
  skip_weekends: false
notify:
  email:
    enabled: false
  lark_bot:
    enabled: false
{extra}
"""


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(config_text(tmp_path), encoding="utf-8")
    return path


@pytest.fixture
def config(config_file: Path) -> Config:
    return load_config(config_file, env={"GITHUB_TOKEN": "test-token"})


def make_client(handler: Handler, **kwargs) -> GitHubClient:
    """构造带 MockTransport 的客户端：不联网、不真实等待。"""

    kwargs.setdefault("retry_interval", 0.0)
    kwargs.setdefault("sleep", lambda _seconds: None)
    kwargs.setdefault("logger", build_logger(None, echo=False))
    return GitHubClient(transport=httpx.MockTransport(handler), **kwargs)


def patch_client(monkeypatch: pytest.MonkeyPatch, module, handler: Handler, **kwargs) -> None:
    """把采集模块的 build_client 替换为"每次调用都新建 Mock 客户端"的工厂。

    采集器内部以 ``with build_client(config) as client`` 使用客户端并会关闭它，
    因此测试必须注入工厂而不是复用同一个实例。
    """

    monkeypatch.setattr(module, "build_client", lambda _config: make_client(handler, **kwargs))


def json_response(payload, status_code: int = 200, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status_code, json=payload, headers=headers or {})


def commit_item(
    sha: str,
    login: str | None,
    email: str,
    moment: str,
    message: str = "feat: 示例提交",
) -> dict:
    return {
        "sha": sha,
        "author": {"login": login} if login else None,
        "commit": {
            "message": message,
            "author": {"date": moment, "email": email, "name": login or email},
            "committer": {"date": moment, "email": email, "name": login or email},
        },
    }


def commit_detail(additions: int, deletions: int, files: int) -> dict:
    return {
        "stats": {"additions": additions, "deletions": deletions, "total": additions + deletions},
        "files": [{"filename": f"file-{index}.py"} for index in range(files)],
    }


def issue_item(
    number: int,
    title: str,
    *,
    state: str = "open",
    created_at: str,
    updated_at: str,
    closed_at: str | None = None,
    assignee: str | None = None,
    pull_request: bool = False,
) -> dict:
    payload = {
        "number": number,
        "title": title,
        "state": state,
        "created_at": created_at,
        "updated_at": updated_at,
        "closed_at": closed_at,
        "assignee": {"login": assignee} if assignee else None,
        "user": {"login": assignee or "someone"},
    }
    if pull_request:
        payload["pull_request"] = {"url": "https://api.github.com/pulls/1"}
    return payload


def comment_item(
    login: str,
    body: str,
    created_at: str,
    *,
    issue_url: str = "https://api.github.com/repos/octo/demo/issues/12",
    html_url: str = "https://github.com/octo/demo/pull/7#discussion_r1",
) -> dict:
    return {
        "user": {"login": login},
        "body": body,
        "created_at": created_at,
        "issue_url": issue_url,
        "html_url": html_url,
    }
