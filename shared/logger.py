"""JSON Lines 日志（design.md §6.3）。

所有事件以一行一条 JSON 的形式落盘，便于日志分析工具解析；
对于密钥类字段做兜底脱敏，避免误把凭据写进日志。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 命中这些关键字的字段一律脱敏（design.md §6.2）
_SECRET_KEYWORDS = ("token", "password", "secret", "webhook", "authorization", "apikey", "api_key")
_REDACTED = "***"


class JsonLineLogger:
    """把结构化事件写成 JSON Lines，同时可选地回显到标准输出。"""

    def __init__(self, log_path: Path | None = None, *, echo: bool = True) -> None:
        self.log_path = Path(log_path) if log_path else None
        self.echo = echo
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def info(self, event: str, **fields: Any) -> None:
        self._write("INFO", event, fields)

    def error(self, event: str, **fields: Any) -> None:
        self._write("ERROR", event, fields)

    def _write(self, level: str, event: str, fields: dict[str, Any]) -> None:
        payload = {
            "time": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "level": level,
            "event": event,
        }
        for key, value in fields.items():
            payload[key] = _sanitize(key, value)
        line = json.dumps(payload, ensure_ascii=False, default=str)
        if self.log_path is not None:
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        if self.echo:
            stream = sys.stderr if level == "ERROR" else sys.stdout
            print(line, file=stream, flush=True)


def _sanitize(key: str, value: Any) -> Any:
    lowered = key.lower()
    if any(keyword in lowered for keyword in _SECRET_KEYWORDS):
        return _REDACTED if value else ""
    # 讨论正文只落统计信息，绝不落全文（design.md §6.2）
    if lowered in {"content", "body"} and isinstance(value, str):
        return f"<{len(value)} chars>"
    return value


def build_logger(log_path: Path | None = None, *, echo: bool = True) -> JsonLineLogger:
    """构造日志器；采集器/推送器内部按需调用，保持接口签名简洁。"""

    return JsonLineLogger(log_path, echo=echo)
