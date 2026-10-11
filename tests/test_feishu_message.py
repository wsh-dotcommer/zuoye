"""飞书群消息采集测试（Task 19 验收）：只统计条数与发言人数，正文永不落盘。"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone

import httpx
import pytest

from collector import feishu_message
from shared.config import FeishuChatConfig, FeishuSourceConfig
from shared.errors import CollectorError
from shared.http import TOKEN_PATH
from tests.conftest import json_response

START = datetime(2026, 9, 17, 16, 0, tzinfo=timezone.utc)
END = datetime(2026, 9, 18, 16, 0, tzinfo=timezone.utc)
MESSAGES_PATH = "/open-apis/im/v1/messages"
SECRET_TEXT = "群聊里的机密内容"


def _ms(moment: datetime) -> str:
    return str(int(moment.timestamp() * 1000))


def _message(
    sender_id: str,
    moment: datetime,
    *,
    sender_type: str = "user",
    msg_type: str = "text",
) -> dict:
    return {
        "message_id": f"om_{sender_id}_{_ms(moment)}",
        "msg_type": msg_type,
        "create_time": _ms(moment),
        "sender": {"id": sender_id, "sender_type": sender_type},
        "body": {"content": SECRET_TEXT},
    }


MESSAGES = [
    _message("ou_a", datetime(2026, 9, 18, 1, 0, tzinfo=timezone.utc)),
    _message("ou_a", datetime(2026, 9, 18, 2, 0, tzinfo=timezone.utc)),
    _message("ou_b", datetime(2026, 9, 18, 3, 0, tzinfo=timezone.utc)),
    _message("ou_bot", datetime(2026, 9, 18, 4, 0, tzinfo=timezone.utc), sender_type="app"),
    _message("ou_b", datetime(2026, 9, 18, 5, 0, tzinfo=timezone.utc), msg_type="system"),
    _message("ou_z", datetime(2026, 9, 19, 1, 0, tzinfo=timezone.utc)),  # 窗口外
]


@pytest.fixture
def feishu_config(config):
    return replace(
        config,
        sources=replace(
            config.sources,
            feishu=FeishuSourceConfig(
                enabled=True,
                app_id="cli_demo",
                app_secret="app-secret",
                chats=(FeishuChatConfig(chat_id="oc_demo", name="智能日报"),),
            ),
        ),
    )


def _handler(seen: list[str], *, page_size: int = 2, token_ok: bool = True, fail_messages: bool = False):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == TOKEN_PATH:
            if not token_ok:
                return json_response({"code": 99991, "msg": "app not found"})
            return json_response({"code": 0, "tenant_access_token": "t-demo", "expire": 7200})
        if request.url.path == MESSAGES_PATH:
            if fail_messages:
                return httpx.Response(500, json={"code": 1, "msg": "server error"})
            page = int(request.url.params.get("page_token") or 0)
            chunk = MESSAGES[page * page_size : (page + 1) * page_size]
            return json_response(
                {
                    "code": 0,
                    "data": {
                        "items": chunk,
                        "has_more": (page + 1) * page_size < len(MESSAGES),
                        "page_token": str(page + 1),
                    },
                }
            )
        return httpx.Response(404, json={"code": 1, "msg": "not found"})

    return handler


def _patch_feishu(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    def factory(config):
        feishu = config.sources.feishu
        return feishu_message.FeishuClient(
            feishu.app_id,
            feishu.app_secret,
            base_url=feishu.base_url,
            transport=httpx.MockTransport(handler),
            retry_times=1,
            retry_interval=0.0,
            sleep=lambda _seconds: None,
        )

    monkeypatch.setattr(feishu_message, "build_client", factory)


def test_collect_counts_messages_and_speakers_without_content(feishu_config, monkeypatch) -> None:
    seen: list[str] = []
    _patch_feishu(monkeypatch, _handler(seen))

    records = feishu_message.collect(feishu_config, START, END)

    assert len(records) == 1
    summary = records[0]
    assert summary.chat_name == "智能日报"
    assert summary.message_count == 3  # 机器人发言与系统消息不计，窗口外那条也不计
    assert summary.speaker_count == 2
    assert feishu_message.total_messages(records) == 3
    # 正文绝不进入模型：记录里搜不到任何群聊文本
    assert SECRET_TEXT not in json.dumps(summary.__dict__, ensure_ascii=False)
    assert not hasattr(summary, "content")


def test_collect_paginates_and_fetches_token_once(feishu_config, monkeypatch) -> None:
    seen: list[str] = []
    _patch_feishu(monkeypatch, _handler(seen, page_size=2))

    feishu_message.collect(feishu_config, START, END)

    assert seen.count(TOKEN_PATH) == 1
    assert seen.count(MESSAGES_PATH) == 3  # 6 条 / 每页 2 条


def test_collect_is_skipped_when_disabled(config, monkeypatch) -> None:
    seen: list[str] = []
    _patch_feishu(monkeypatch, _handler(seen))

    assert feishu_message.collect(config, START, END) == []
    assert seen == []  # 关掉数据源时一个请求都不发


def test_app_credentials_failure_raises_collector_error(feishu_config, monkeypatch) -> None:
    _patch_feishu(monkeypatch, _handler([], token_ok=False))

    with pytest.raises(CollectorError):
        feishu_message.collect(feishu_config, START, END)


def test_message_endpoint_failure_is_retried_then_raised(feishu_config, monkeypatch) -> None:
    seen: list[str] = []
    _patch_feishu(monkeypatch, _handler(seen, fail_messages=True))

    with pytest.raises(CollectorError):
        feishu_message.collect(feishu_config, START, END)

    assert seen.count(MESSAGES_PATH) == 2  # 首次 + 重试 1 次


def test_business_error_code_in_body_is_treated_as_failure(feishu_config, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == TOKEN_PATH:
            return json_response({"code": 0, "tenant_access_token": "t-demo"})
        return json_response({"code": 99991663, "msg": "no permission"})

    _patch_feishu(monkeypatch, handler)

    with pytest.raises(CollectorError):
        feishu_message.collect(feishu_config, START, END)
