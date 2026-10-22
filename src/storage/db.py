"""
SQLite 持久化存储：内容去重、运行历史
"""
import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger("zhihu_analyst")

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_content (
    content_id   TEXT PRIMARY KEY,
    content_type TEXT NOT NULL,
    fetch_date   TEXT NOT NULL,
    is_relevant  INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS run_history (
    run_date         TEXT PRIMARY KEY,
    items_fetched    INTEGER DEFAULT 0,
    items_relevant   INTEGER DEFAULT 0,
    claude_input_tk  INTEGER DEFAULT 0,
    claude_output_tk INTEGER DEFAULT 0,
    claude_cost_usd  REAL DEFAULT 0.0,
    success          INTEGER DEFAULT 1,
    error_msg        TEXT,
    ran_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


class Database:
    def __init__(self, db_path: str = "output/seen_content.db"):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()
        logger.debug(f"数据库已连接：{db_path}")

    def _init_schema(self):
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def is_seen(self, content_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM seen_content WHERE content_id = ?", (content_id,)
        ).fetchone()
        return row is not None

    def mark_seen(self, content_id: str, content_type: str, is_relevant: bool):
        self.conn.execute(
            "INSERT OR IGNORE INTO seen_content "
            "(content_id, content_type, fetch_date, is_relevant) VALUES (?,?,?,?)",
            (content_id, content_type, _today_str(), 1 if is_relevant else 0)
        )
        self.conn.commit()

    def mark_seen_batch(self, items: list):
        today = _today_str()
        self.conn.executemany(
            "INSERT OR IGNORE INTO seen_content "
            "(content_id, content_type, fetch_date, is_relevant) VALUES (?,?,?,?)",
            [(cid, ctype, today, 1 if rel else 0) for cid, ctype, rel in items]
        )
        self.conn.commit()

    def cleanup_old(self, retention_days: int = 7):
        cutoff = (datetime.now() - timedelta(days=retention_days)).strftime("%Y-%m-%d")
        cursor = self.conn.execute(
            "DELETE FROM seen_content WHERE fetch_date < ?", (cutoff,)
        )
        self.conn.commit()
        if cursor.rowcount > 0:
            logger.info(f"清理 {cursor.rowcount} 条旧内容记录（早于 {cutoff}）")

    def record_run(
        self,
        run_date: str,
        items_fetched: int,
        items_relevant: int,
        cost_tracker: dict,
        success: bool = True,
        error_msg: str = None
    ):
        self.conn.execute(
            "INSERT OR REPLACE INTO run_history "
            "(run_date, items_fetched, items_relevant, claude_input_tk, "
            " claude_output_tk, claude_cost_usd, success, error_msg) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                run_date,
                items_fetched,
                items_relevant,
                cost_tracker.get("input_tokens", 0),
                cost_tracker.get("output_tokens", 0),
                cost_tracker.get("cost_usd", 0.0),
                1 if success else 0,
                error_msg
            )
        )
        self.conn.commit()

    def get_last_run(self) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM run_history ORDER BY ran_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def close(self):
        self.conn.close()
