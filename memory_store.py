import json
import os
import sqlite3
from typing import Any, Dict, List, Optional


class AuditMemoryStore:
    def __init__(self, db_path: Optional[str] = None):
        data_dir = os.path.abspath("./data")
        os.makedirs(data_dir, exist_ok=True)
        self.db_path = db_path or os.path.join(data_dir, "audit_memory.db")
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        existing = {row["name"] for row in rows}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS audit_records (
                    order_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    buyer TEXT,
                    gift_name TEXT,
                    status TEXT NOT NULL,
                    abnormal INTEGER NOT NULL DEFAULT 0,
                    abnormal_streak INTEGER NOT NULL DEFAULT 0,
                    report TEXT NOT NULL,
                    order_payload TEXT NOT NULL,
                    audited_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS user_states (
                    user_id TEXT PRIMARY KEY,
                    user_name TEXT,
                    abnormal_streak INTEGER NOT NULL DEFAULT 0,
                    last_status TEXT,
                    last_report TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS blacklist_entries (
                    user_id TEXT PRIMARY KEY,
                    user_name TEXT,
                    reason TEXT NOT NULL,
                    source TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    added_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    removed_at TEXT
                );
                """
            )
            self._ensure_column(conn, "audit_records", "user_id", "TEXT")
            self._ensure_column(conn, "audit_records", "abnormal", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "audit_records", "abnormal_streak", "INTEGER NOT NULL DEFAULT 0")
            conn.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_audit_records_user_id
                ON audit_records (user_id);

                CREATE INDEX IF NOT EXISTS idx_audit_records_buyer
                ON audit_records (buyer);

                CREATE INDEX IF NOT EXISTS idx_audit_records_audited_at
                ON audit_records (audited_at DESC);

                CREATE INDEX IF NOT EXISTS idx_blacklist_active
                ON blacklist_entries (is_active, updated_at DESC);
                """
            )

    def has_processed_order(self, order_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM audit_records WHERE order_id = ?",
                (str(order_id),),
            ).fetchone()
        return row is not None

    def save_audit_record(
        self,
        order_id: str,
        user_id: str,
        order_data: Dict[str, Any],
        report: str,
        status: str,
        abnormal: bool = False,
        abnormal_streak: int = 0,
    ) -> None:
        payload = json.dumps(order_data, ensure_ascii=False)
        buyer = str(order_data.get("buyer", "未知用户"))
        gift_name = str(order_data.get("giftName", "N/A"))

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO audit_records (
                    order_id,
                    user_id,
                    buyer,
                    gift_name,
                    status,
                    abnormal,
                    abnormal_streak,
                    report,
                    order_payload,
                    audited_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    str(order_id),
                    str(user_id),
                    buyer,
                    gift_name,
                    status,
                    int(bool(abnormal)),
                    int(abnormal_streak),
                    report,
                    payload,
                ),
            )

    def get_record(self, order_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM audit_records WHERE order_id = ?",
                (str(order_id),),
            ).fetchone()
        return dict(row) if row else None

    def search_records(self, query: str = "", limit: int = 10) -> List[Dict[str, Any]]:
        limit = max(1, int(limit))
        normalized_query = str(query or "").strip()

        with self._connect() as conn:
            if normalized_query:
                pattern = f"%{normalized_query}%"
                rows = conn.execute(
                    """
                    SELECT *
                    FROM audit_records
                    WHERE order_id LIKE ?
                       OR user_id LIKE ?
                       OR buyer LIKE ?
                       OR gift_name LIKE ?
                       OR report LIKE ?
                    ORDER BY audited_at DESC
                    LIMIT ?
                    """,
                    (pattern, pattern, pattern, pattern, pattern, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM audit_records
                    ORDER BY audited_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()

        return [dict(row) for row in rows]

    def update_user_state(
        self,
        user_id: str,
        user_name: str,
        status: str,
        report: str,
        abnormal: bool,
    ) -> int:
        current = self.get_user_state(user_id)
        if abnormal:
            next_streak = int(current.get("abnormal_streak", 0)) + 1 if current else 1
        else:
            next_streak = 0

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_states (
                    user_id,
                    user_name,
                    abnormal_streak,
                    last_status,
                    last_report,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    user_name = excluded.user_name,
                    abnormal_streak = excluded.abnormal_streak,
                    last_status = excluded.last_status,
                    last_report = excluded.last_report,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (str(user_id), user_name, next_streak, status, report),
            )

        return next_streak

    def get_user_state(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM user_states WHERE user_id = ?",
                (str(user_id),),
            ).fetchone()
        return dict(row) if row else None

    def add_to_blacklist(self, user_id: str, user_name: str, reason: str, source: str = "manual") -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO blacklist_entries (
                    user_id,
                    user_name,
                    reason,
                    source,
                    is_active,
                    added_at,
                    updated_at,
                    removed_at
                )
                VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL)
                ON CONFLICT(user_id) DO UPDATE SET
                    user_name = excluded.user_name,
                    reason = excluded.reason,
                    source = excluded.source,
                    is_active = 1,
                    updated_at = CURRENT_TIMESTAMP,
                    removed_at = NULL
                """,
                (str(user_id), user_name, reason, source),
            )

    def remove_from_blacklist(self, user_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE blacklist_entries
                SET is_active = 0,
                    updated_at = CURRENT_TIMESTAMP,
                    removed_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
                """,
                (str(user_id),),
            )

    def is_blacklisted(self, user_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM blacklist_entries
                WHERE user_id = ? AND is_active = 1
                """,
                (str(user_id),),
            ).fetchone()
        return row is not None

    def list_blacklist(self, active_only: bool = True) -> List[Dict[str, Any]]:
        query = """
            SELECT *
            FROM blacklist_entries
        """
        params: tuple[Any, ...] = ()
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY updated_at DESC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
