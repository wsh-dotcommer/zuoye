"""飞书群机器人推送（design.md §4.4，Task 8；签名与自检为 Task 12 v1.2）。

接口契约：
    send(report, target) -> bool
    check(target) -> tuple[bool, str]
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from shared.logger import JsonLineLogger, build_logger
from shared.models import DailyReport

RETRY_TIMES = 2
HTTP_TIMEOUT_SECONDS = 15
MAX_MARKDOWN_LENGTH = 4000
SIGN_FAILED_HINT = (
    "飞书机器人启用了「签名校验」：请在 .env 填 LARK_BOT_SECRET，"
    "并把 config.yaml 的 notify.lark_bot.secret 写成 ${LARK_BOT_SECRET}"
)


@dataclass(frozen=True)
class LarkBotTarget:
    """飞书自定义机器人 Webhook（由环境变量注入）。

    ``secret`` 为可选：机器人安全设置选「签名校验」时必填；
    选「自定义关键词」或「IP 白名单」时留空即可。
    """

    webhook: str
    secret: str = ""


def send(
    report: DailyReport,
    target: LarkBotTarget,
    *,
    client: httpx.Client | None = None,
    retry_times: int = RETRY_TIMES,
    logger: JsonLineLogger | None = None,
) -> bool:
    """把 Markdown 日报作为飞书消息卡片推送，失败重试 2 次后返回 False。"""

    return _post(
        target.webhook,
        build_payload(report, secret=target.secret),
        client=client,
        retry_times=retry_times,
        logger=logger or build_logger(None),
        event="lark_bot",
    )


def check(
    target: LarkBotTarget,
    *,
    client: httpx.Client | None = None,
    logger: JsonLineLogger | None = None,
) -> tuple[bool, str]:
    """连通性自检：往群里发一条纯文本消息，返回 ``(是否成功, 人类可读说明)``。

    自检消息与正式日报走同一个 Webhook、同一套签名逻辑，
    便于在 ``--dry-run``（不推送）之外单独确认通道是否打通。
    """

    text = f"智能日报 · 飞书机器人连通性自检 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    payload: dict[str, Any] = {
        "msg_type": "text",
        "content": {"text": text},
    }
    ok = _post(
        target.webhook,
        _sign(payload, target.secret),
        client=client,
        retry_times=0,
        logger=logger or build_logger(None),
        event="lark_bot_check",
    )
    if ok:
        return True, "飞书机器人连通性正常：群里应该已经收到「智能日报 · 飞书机器人连通性自检」"
    return False, (
        "飞书机器人自检失败：请检查 Webhook 是否完整、机器人是否还在群里，"
        "以及安全设置是否匹配（签名校验需配 secret；自定义关键词建议填「日报」）。"
        "详细返回体见 logs/daily-report.jsonl"
    )


def build_payload(
    report: DailyReport,
    *,
    secret: str = "",
    timestamp: int | None = None,
) -> dict[str, Any]:
    """构造飞书消息卡片（lark_md 支持 Markdown 渲染）；配置 secret 时附加签名。"""

    content = report.markdown or "（日报内容为空）"
    if len(content) > MAX_MARKDOWN_LENGTH:
        content = content[:MAX_MARKDOWN_LENGTH] + "\n…（内容过长已截断）"
    payload: dict[str, Any] = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"{report.team_name} · {report.date.isoformat()} 智能日报",
                }
            },
            "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": content}}],
        },
    }
    return _sign(payload, secret, timestamp)


def _sign(payload: dict[str, Any], secret: str, timestamp: int | None = None) -> dict[str, Any]:
    """启用签名校验时必须随载荷附带 timestamp 与 sign，否则飞书返回 19021。"""

    if not secret:
        return payload
    ts = timestamp if timestamp is not None else int(time.time())
    payload["timestamp"] = str(ts)
    payload["sign"] = gen_sign(ts, secret)
    return payload


def gen_sign(timestamp: int, secret: str) -> str:
    """飞书官方签名算法：对 ``"{timestamp}\\n{secret}"`` 做 HMAC-SHA256 后 Base64。"""

    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _post(
    webhook: str,
    payload: dict[str, Any],
    *,
    client: httpx.Client | None,
    retry_times: int,
    logger: JsonLineLogger,
    event: str,
) -> bool:
    attempts = retry_times + 1
    owns_client = client is None
    http_client = client or httpx.Client(timeout=HTTP_TIMEOUT_SECONDS)

    try:
        for attempt in range(1, attempts + 1):
            try:
                response = http_client.post(webhook, json=payload)
                if _is_success(response):
                    logger.info(f"{event}_sent", status=response.status_code)
                    return True
                fields: dict[str, Any] = {
                    "attempt": attempt,
                    "status": response.status_code,
                    "body": response.text[:200],
                }
                hint = _failure_hint(response)
                if hint:
                    fields["hint"] = hint
                logger.error(f"{event}_send_failed", **fields)
            except httpx.HTTPError as exc:
                logger.error(f"{event}_send_error", attempt=attempt, error=str(exc))
        return False
    finally:
        if owns_client:
            http_client.close()


def _failure_hint(response: httpx.Response) -> str:
    """把飞书常见错误码翻译成一句可执行的排查提示。"""

    try:
        body = response.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    code = body.get("code", body.get("StatusCode"))
    if code in (19021, "19021"):
        return SIGN_FAILED_HINT
    if code in (19024, "19024"):
        return "飞书机器人设置了「自定义关键词」：消息里必须包含该关键词（建议填「日报」）"
    if code in (19001, "19001"):
        return "飞书提示参数错误：确认 Webhook 地址完整（形如 .../bot/v2/hook/xxxx）"
    return ""


def _is_success(response: httpx.Response) -> bool:
    if response.status_code != 200:
        return False
    try:
        body = response.json()
    except ValueError:
        return True
    if not isinstance(body, dict):
        return True
    for key in ("code", "StatusCode"):
        if key in body and body[key] not in (0, "0"):
            return False
    return True
