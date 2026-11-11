"""
database/init_db.py — Self-Healing SQLite Database Initializer and Connection Manager.

Checks for database existence on startup, initializes schemas automatically,
enables WAL (Write-Ahead Logging) mode with robust timeouts, and heals missing tables.
"""
from __future__ import annotations

import logging
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

# Add root directory to sys.path if invoked standalone
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config.settings import settings

logger = logging.getLogger("database.init_db")


class DatabaseManager:
    """Manages SQLite connections, self-healing initialization, and migrations."""

    def __init__(self, db_path: Path | None = None, schema_path: Path | None = None) -> None:
        self.db_path = Path(db_path or settings.db_path)
        self.schema_path = Path(schema_path or (BASE_DIR / "database" / "schema.sql"))

    def exists(self) -> bool:
        """Check if the SQLite database file currently exists and is non-empty."""
        return self.db_path.exists() and self.db_path.stat().st_size > 0

    def initialize_database(self) -> bool:
        """
        Self-healing initializer:
        1. Ensures the target directory exists.
        2. Creates database file if missing.
        3. Configures WAL mode and busy timeout for concurrent safety.
        4. Applies database/schema.sql to set up tables and indexes.
        """
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        is_new_db = not self.exists()

        if is_new_db:
            logger.info("Database file not found at '%s'. Executing self-healing first-time setup...", self.db_path)
        else:
            logger.debug("Existing database detected at '%s'. Verifying schema integrity...", self.db_path)

        if not self.schema_path.exists():
            raise FileNotFoundError(f"Schema definition file not found at: {self.schema_path}")

        schema_sql = self.schema_path.read_text(encoding="utf-8")

        with self.get_connection() as conn:
            # Enable WAL mode for high concurrency and resilience
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA busy_timeout = 30000;")
            conn.execute("PRAGMA foreign_keys = ON;")
            
            # Execute schema DDL (uses CREATE TABLE IF NOT EXISTS)
            conn.executescript(schema_sql)
            conn.commit()

        if is_new_db:
            logger.info("Self-healing database initialization completed successfully at '%s'.", self.db_path)
        else:
            logger.debug("Database schema verified and up-to-date.")

        return True

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager providing a configured SQLite connection with row factories."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def check_health(self) -> dict:
        """Audit database health, table row counts, and schema state."""
        self.initialize_database()
        stats = {}
        with self.get_connection() as conn:
            cursor = conn.cursor()
            tables = cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
            ).fetchall()
            for t in tables:
                table_name = t["name"]
                count = cursor.execute(f"SELECT COUNT(*) as c FROM {table_name};").fetchone()["c"]
                stats[table_name] = count
        return stats


# Global manager instance
db_manager = DatabaseManager()


def get_db_connection() -> Generator[sqlite3.Connection, None, None]:
    """Helper generator for acquiring a database connection."""
    return db_manager.get_connection()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    print(f"Initializing database at: {settings.db_path}")
    db_manager.initialize_database()
    health = db_manager.check_health()
    print("Database Health Summary:")
    for tbl, count in health.items():
        print(f"  - Table [{tbl}]: {count} records")
    print("Initialization verified.")
