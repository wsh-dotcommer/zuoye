"""SQLite 日报历史存储（design.md §2、§4.3）。

同一日期重复执行按主键覆盖，保证幂等（design.md §6.3）。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from shared.models import DailyReport

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    report_date   TEXT PRIMARY KEY,
    team_name     TEXT NOT NULL,
    member_count  INTEGER NOT NULL,
    generated_at  TEXT NOT NULL,
    site_file     TEXT NOT NULL,
    markdown      TEXT NOT NULL,
    html          TEXT NOT NULL
)
"""


@dataclass(frozen=True)
class HistoryEntry:
    """静态站索引页需要的历史条目。"""

    date: date
    team_name: str
    member_count: int
    generated_at: datetime
    site_file: str
    markdown: str


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

    def save(self, report: DailyReport, site_file: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO reports (report_date, team_name, member_count, generated_at, site_file, markdown, html)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(report_date) DO UPDATE SET
                    team_name = excluded.team_name,
                    member_count = excluded.member_count,
                    generated_at = excluded.generated_at,
                    site_file = excluded.site_file,
                    markdown = excluded.markdown,
                    html = excluded.html
                """,
                (
                    report.date.isoformat(),
                    report.team_name,
                    len(report.members),
                    report.generated_at.isoformat(),
                    site_file,
                    report.markdown,
                    report.html,
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
        return [
            HistoryEntry(
                date=date.fromisoformat(row["report_date"]),
                team_name=row["team_name"],
                member_count=int(row["member_count"]),
                generated_at=datetime.fromisoformat(row["generated_at"]),
                site_file=row["site_file"],
                markdown=row["markdown"],
            )
            for row in rows
        ]

    def get(self, day: date) -> HistoryEntry | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM reports WHERE report_date = ?", (day.isoformat(),)
            ).fetchone()
        if row is None:
            return None
        return HistoryEntry(
            date=date.fromisoformat(row["report_date"]),
            team_name=row["team_name"],
            member_count=int(row["member_count"]),
            generated_at=datetime.fromisoformat(row["generated_at"]),
            site_file=row["site_file"],
            markdown=row["markdown"],
        )
