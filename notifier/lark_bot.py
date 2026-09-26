"""飞书群机器人推送（design.md §4.4，Task 8）。

接口契约：
    send(report, target) -> bool
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from shared.logger import JsonLineLogger, build_logger
from shared.models import DailyReport

RETRY_TIMES = 2
HTTP_TIMEOUT_SECONDS = 15
MAX_MARKDOWN_LENGTH = 4000


@dataclass(frozen=True)
class LarkBotTarget:
    """飞书自定义机器人 Webhook（由环境变量注入）。"""

    webhook: str


def send(
    report: DailyReport,
    target: LarkBotTarget,
    *,
    client: httpx.Client | None = None,
    retry_times: int = RETRY_TIMES,
    logger: JsonLineLogger | None = None,
) -> bool:
    """把 Markdown 日报作为飞书消息卡片推送，失败重试 2 次后返回 False。"""

    log = logger or build_logger(None)
    payload = build_payload(report)
    attempts = retry_times + 1
    owns_client = client is None
    http_client = client or httpx.Client(timeout=HTTP_TIMEOUT_SECONDS)

    try:
        for attempt in range(1, attempts + 1):
            try:
                response = http_client.post(target.webhook, json=payload)
                if _is_success(response):
                    log.info("lark_bot_sent", status=response.status_code)
                    return True
                log.error(
                    "lark_bot_send_failed",
                    attempt=attempt,
                    status=response.status_code,
                    body=response.text[:120],
                )
            except httpx.HTTPError as exc:
                log.error("lark_bot_send_error", attempt=attempt, error=str(exc))
        return False
    finally:
        if owns_client:
            http_client.close()


def build_payload(report: DailyReport) -> dict[str, Any]:
    """构造飞书消息卡片（lark_md 支持 Markdown 渲染）。"""

    content = report.markdown or "（日报内容为空）"
    if len(content) > MAX_MARKDOWN_LENGTH:
        content = content[:MAX_MARKDOWN_LENGTH] + "\n…（内容过长已截断）"
    return {
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
