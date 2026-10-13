"""SQLite 日报历史存储（design.md §2、§4.3）。

同一日期重复执行按主键覆盖，保证幂等（design.md §6.3）。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from shared.models import DailyReport, ReportStats

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    report_date   TEXT PRIMARY KEY,
    team_name     TEXT NOT NULL,
    member_count  INTEGER NOT NULL,
    generated_at  TEXT NOT NULL,
    site_file     TEXT NOT NULL,
    markdown      TEXT NOT NULL,
    html          TEXT NOT NULL,
    commit_count       INTEGER,
    task_count         INTEGER,
    message_count      INTEGER,
    chat_message_count INTEGER,
    total_hours        REAL
)
"""

# v2.3 迁移：结构化统计列。旧库用 ALTER TABLE 补齐，旧行保持 NULL（表示"无可比数据"）
_STATS_COLUMNS: tuple[tuple[str, str], ...] = (
    ("commit_count", "INTEGER"),
    ("task_count", "INTEGER"),
    ("message_count", "INTEGER"),
    ("chat_message_count", "INTEGER"),
    ("total_hours", "REAL"),
)


@dataclass(frozen=True)
class HistoryEntry:
    """静态站索引页需要的历史条目。"""

    date: date
    team_name: str
    member_count: int
    generated_at: datetime
    site_file: str
    markdown: str
    commit_count: int | None = None
    task_count: int | None = None
    message_count: int | None = None
    chat_message_count: int | None = None
    total_hours: float | None = None

    def to_stats(self) -> ReportStats | None:
        """转成趋势/对比用的结构化统计；旧行（无统计列）返回 None。"""

        if self.commit_count is None and self.total_hours is None:
            return None
        return ReportStats(
            date=self.date,
            commit_count=int(self.commit_count or 0),
            task_count=int(self.task_count or 0),
            message_count=int(self.message_count or 0),
            chat_message_count=int(self.chat_message_count or 0),
            total_hours=float(self.total_hours or 0.0),
        )


class Storage:
    """日报历史的读写入口。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(_SCHEMA)
            _migrate(connection)

    def save(self, report: DailyReport, site_file: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO reports (
                    report_date, team_name, member_count, generated_at, site_file, markdown, html,
                    commit_count, task_count, message_count, chat_message_count, total_hours
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(report_date) DO UPDATE SET
                    team_name = excluded.team_name,
                    member_count = excluded.member_count,
                    generated_at = excluded.generated_at,
                    site_file = excluded.site_file,
                    markdown = excluded.markdown,
                    html = excluded.html,
                    commit_count = excluded.commit_count,
                    task_count = excluded.task_count,
                    message_count = excluded.message_count,
                    chat_message_count = excluded.chat_message_count,
                    total_hours = excluded.total_hours
                """,
                (
                    report.date.isoformat(),
                    report.team_name,
                    len(report.members),
                    report.generated_at.isoformat(),
                    site_file,
                    report.markdown,
                    report.html,
                    report.commit_count,
                    report.task_count,
                    report.message_count,
                    report.chat_message_count,
                    round(report.total_hours, 2),
                ),
            )

    def list_reports(self, limit: int | None = None) -> list[HistoryEntry]:
        query = "SELECT * FROM reports ORDER BY report_date DESC"
        params: tuple[object, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            params = (limit,)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_entry(row) for row in rows]

    def get(self, day: date) -> HistoryEntry | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM reports WHERE report_date = ?", (day.isoformat(),)
            ).fetchone()
        if row is None:
            return None
        return _entry(row)


def _migrate(connection: sqlite3.Connection) -> None:
    """补齐 v2.3 新增的统计列（幂等；列名是本模块常量，不做字符串拼接外部输入）。"""

    existing = {row["name"] for row in connection.execute("PRAGMA table_info(reports)")}
    for name, kind in _STATS_COLUMNS:
        if name not in existing:
            connection.execute(f"ALTER TABLE reports ADD COLUMN {name} {kind}")


def _entry(row: sqlite3.Row) -> HistoryEntry:
    keys = row.keys()
    hours = row["total_hours"] if "total_hours" in keys else None
    return HistoryEntry(
        date=date.fromisoformat(row["report_date"]),
        team_name=row["team_name"],
        member_count=int(row["member_count"]),
        generated_at=datetime.fromisoformat(row["generated_at"]),
        site_file=row["site_file"],
        markdown=row["markdown"],
        commit_count=_optional_int(row, "commit_count"),
        task_count=_optional_int(row, "task_count"),
        message_count=_optional_int(row, "message_count"),
        chat_message_count=_optional_int(row, "chat_message_count"),
        total_hours=None if hours is None else float(hours),
    )


def _optional_int(row: sqlite3.Row, key: str) -> int | None:
    if key not in row.keys():
        return None
    value = row[key]
    return None if value is None else int(value)
