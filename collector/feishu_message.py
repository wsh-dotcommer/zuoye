"""飞书群消息采集（v2.3）：只产出"条数与发言人数"。

接口契约：
    collect(config, start, end) -> list[ChatSummaryRecord]

隐私边界（design.md §6.6）：正文在采集器里就地丢弃——不写模型、不写日志、
不进任何产物与页面。这里只保留群名、窗口内的消息条数与去重发言人数。
"""

from __future__ import annotations

from datetime import datetime, timezone

from shared.config import Config, FeishuChatConfig
from shared.errors import CollectorError
from shared.http import FeishuClient
from shared.logger import JsonLineLogger, build_logger
from shared.models import ChatSummaryRecord

MESSAGES_PATH = "/open-apis/im/v1/messages"
PAGE_SIZE = 50
MAX_PAGES = 20


def build_client(config: Config) -> FeishuClient:
    """构造飞书客户端；测试通过替换本函数注入 MockTransport。"""

    feishu = config.sources.feishu
    return FeishuClient(
        feishu.app_id,
        feishu.app_secret,
        base_url=feishu.base_url,
        retry_times=feishu.retry_times,
        timeout=feishu.timeout_seconds,
        logger=build_logger(config.report.log_path, echo=False),
    )


def total_messages(records: list[ChatSummaryRecord]) -> int:
    """数据源徽章用的条数：飞书源统计的是"消息总条数"而不是"群数量"。"""

    return sum(item.message_count for item in records)


def collect(config: Config, start: datetime, end: datetime) -> list[ChatSummaryRecord]:
    """采集配置里每个群的当日汇总；未启用时直接返回空列表。"""

    feishu = config.sources.feishu
    if not feishu.enabled or not feishu.chats:
        return []

    logger = build_logger(config.report.log_path, echo=False)
    summaries: list[ChatSummaryRecord] = []
    with build_client(config) as client:
        for chat in feishu.chats:
            count, speakers, exhausted = _summarize(client, chat, start, end, logger)
            if exhausted:
                logger.error("feishu_pages_exhausted", chat=chat.name, limit=MAX_PAGES)
            logger.info(
                "feishu_chat_collected",
                chat=chat.name,
                count=count,
                speakers=len(speakers),
            )
            summaries.append(
                ChatSummaryRecord(
                    chat_name=chat.name,
                    message_count=count,
                    speaker_count=len(speakers),
                )
            )
    return summaries


def _summarize(
    client: FeishuClient,
    chat: FeishuChatConfig,
    start: datetime,
    end: datetime,
    logger: JsonLineLogger,
) -> tuple[int, set[str], bool]:
    """翻页统计一个群：返回 (条数, 发言人去重集合, 是否触顶页数上限)。"""

    speakers: set[str] = set()
    total = 0
    page_token = ""
    pages = 0
    while pages < MAX_PAGES:
        params = {
            "container_id_type": "chat",
            "container_id": chat.chat_id,
            "start_time": str(int(start.timestamp())),
            "end_time": str(int(end.timestamp())),
            "sort_type": "ByCreateTimeAsc",
            "page_size": PAGE_SIZE,
        }
        if page_token:
            params["page_token"] = page_token
        try:
            data = client.get_json(MESSAGES_PATH, params) or {}
        except CollectorError as exc:
            logger.error("feishu_chat_failed", chat=chat.name, error=str(exc))
            raise
        pages += 1
        for item in data.get("items") or []:
            moment = _message_time(item)
            if moment is not None and not (start <= moment < end):
                continue  # 接口时间参数为闭区间，这里按左闭右开再裁一次
            if not _is_countable(item):
                continue
            total += 1
            speaker = str((item.get("sender") or {}).get("id") or "")
            if speaker:
                speakers.add(speaker)
        page_token = str(data.get("page_token") or "")
        if not data.get("has_more") or not page_token:
            break
    return total, speakers, pages >= MAX_PAGES


def _is_countable(item: dict) -> bool:
    """只数真人发的普通消息：跳过应用/机器人发言与系统消息。"""

    if str(item.get("msg_type") or "") == "system":
        return False
    sender = item.get("sender") or {}
    return str(sender.get("sender_type") or "") == "user"


def _message_time(item: dict) -> datetime | None:
    """飞书 create_time 是毫秒级时间戳字符串。"""

    raw = str(item.get("create_time") or "")
    if not raw.isdigit():
        return None
    return datetime.fromtimestamp(int(raw) / 1000, tz=timezone.utc)
