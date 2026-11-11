"""
app/post_email_tracker.py — Database tracking for LinkedIn post email applications.

Tracks which LinkedIn posts have already been emailed so we never double-send.
Part of the Job Agent Framework — d:/job-agent
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


class PostEmailTracker:
    """
    Tracks LinkedIn post email applications in a dedicated SQLite table.
    Uses the same jobs.db database as the main JobTracker for consolidated storage.
    """

    TABLE_DDL = """
    CREATE TABLE IF NOT EXISTS linkedin_post_emails (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        post_url     TEXT    NOT NULL,
        poster_name  TEXT,
        company      TEXT,
        role         TEXT,
        email_to     TEXT,
        email_subject TEXT,
        email_body   TEXT,
        sent_at      TEXT,
        status       TEXT    NOT NULL DEFAULT 'pending',
        reason       TEXT,
        created_at   TEXT    NOT NULL,
        post_age     TEXT,
        UNIQUE(post_url, email_to)
    )
    """

    def __init__(self, db_path: Path, logger=None) -> None:
        self.db_path = db_path
        self.logger = logger

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA busy_timeout = 30000")
        except Exception:
            pass
        try:
            yield conn
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def init_table(self) -> None:
        """Create the linkedin_post_emails table if it does not exist."""
        with self._connect() as conn:
            conn.execute(self.TABLE_DDL)
            # Migrations: add columns if missing (idempotent)
            columns = {row["name"] if isinstance(row, sqlite3.Row) else row[1] for row in conn.execute("PRAGMA table_info(linkedin_post_emails)")}
            migration_cols = [
                ("email_body", "TEXT"),
                ("sent_at", "TEXT"),
                ("post_age", "TEXT"),
            ]
            for col_name, col_type in migration_cols:
                if col_name not in columns:
                    conn.execute(f"ALTER TABLE linkedin_post_emails ADD COLUMN {col_name} {col_type}")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_post_emails_status ON linkedin_post_emails(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_post_emails_email_to ON linkedin_post_emails(email_to)")
            conn.commit()

    def is_already_sent(self, post_url: str, email_to: str) -> bool:
        """Return True if we've already sent an application email for this post+recipient."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM linkedin_post_emails WHERE post_url = ? AND email_to = ? AND status = 'sent'",
                (post_url, email_to),
            ).fetchone()
        return row is not None

    def record_attempt(
        self,
        post_url: str,
        poster_name: str,
        company: str,
        role: str,
        email_to: str,
        email_subject: str,
        email_body: str,
        status: str,
        reason: str = "",
        post_age: str = "",
    ) -> None:
        """Insert or update a record for a post email application attempt."""
        now = datetime.utcnow().isoformat()
        sent_at = now if status == "sent" else None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO linkedin_post_emails
                    (post_url, poster_name, company, role, email_to, email_subject,
                     email_body, sent_at, status, reason, post_age, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(post_url, email_to) DO UPDATE SET
                    poster_name  = excluded.poster_name,
                    company      = excluded.company,
                    role         = excluded.role,
                    email_subject= excluded.email_subject,
                    email_body   = excluded.email_body,
                    sent_at      = excluded.sent_at,
                    status       = excluded.status,
                    reason       = excluded.reason,
                    post_age     = excluded.post_age
                """,
                (post_url, poster_name, company, role, email_to, email_subject,
                 email_body, sent_at, status, reason, post_age, now),
            )
            conn.commit()

    def get_all_sent(self) -> list[dict]:
        """Return all successfully sent email records."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM linkedin_post_emails WHERE status = 'sent' ORDER BY sent_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self) -> dict:
        """Return a summary of all tracked post email activity."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM linkedin_post_emails GROUP BY status"
            ).fetchall()
        return {row["status"]: row["cnt"] for row in rows}
