"""SQLite persistence — single file, no ORM boilerplate."""

import sqlite3
from datetime import datetime
from typing import List, Optional

from app.settings import settings
from app.schemas.classification import ApprovalStatus, EmailRecord


class Database:
    def __init__(self) -> None:
        settings.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(settings.DB_PATH), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._create_tables()

    def _create_tables(self) -> None:
        """Initialize tables using standard SQL."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS processed_emails (
                email_id   TEXT PRIMARY KEY,
                thread_id  TEXT NOT NULL,
                status     TEXT NOT NULL,
                payload    TEXT NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """)
        # email_id PRIMARY KEY already enforces uniqueness;
        # explicit index makes intent clear and speeds up lookups.
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_thread_id ON processed_emails (thread_id)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON processed_emails (status)")
        self.conn.commit()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save(self, record: EmailRecord) -> None:
        """
        Upsert — safe for concurrent writes thanks to ON CONFLICT + UNIQUE index.
        Note: two simultaneous first-inserts of the same email_id may still cause
        a sqlite3.IntegrityError under extreme concurrency; that is acceptable MVP behavior.
        """
        sql = """
            INSERT INTO processed_emails (email_id, thread_id, status, payload, updated_at)
            VALUES (:email_id, :thread_id, :status, :payload, :updated_at)
            ON CONFLICT(email_id) DO UPDATE SET
                status     = excluded.status,
                payload    = excluded.payload,
                updated_at = excluded.updated_at
        """
        params = {
            "email_id":   record.email_id,
            "thread_id":  record.thread_id,
            "status":     record.status.value,
            "payload":    record.model_dump_json(),
            "updated_at": datetime.now().isoformat(),  # ISO string is safer for SQLite
        }
        with self.conn:
            self.conn.execute(sql, params)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def find_by_id(self, email_id: str) -> Optional[EmailRecord]:
        """Direct lookup by primary key."""
        row = self.conn.execute(
            "SELECT payload FROM processed_emails WHERE email_id = ?",
            (email_id,),
        ).fetchone()
        return EmailRecord.model_validate_json(row["payload"]) if row else None

    def find_by_thread_id(self, thread_id: str) -> Optional[EmailRecord]:
        """Key for matching manager's approval reply back to the original email."""
        row = self.conn.execute(
            "SELECT payload FROM processed_emails WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        return EmailRecord.model_validate_json(row["payload"]) if row else None

    def list_by_status(self, status: ApprovalStatus) -> List[EmailRecord]:
        """Filtered lookup using the indexed status column."""
        rows = self.conn.execute(
            "SELECT payload FROM processed_emails WHERE status = ?",
            (status.value,),
        ).fetchall()
        return [EmailRecord.model_validate_json(r["payload"]) for r in rows]

    def list_all(self) -> List[EmailRecord]:
        rows = self.conn.execute("SELECT payload FROM processed_emails").fetchall()
        return [EmailRecord.model_validate_json(r["payload"]) for r in rows]

    def close(self) -> None:
        self.conn.close()


db = Database()
