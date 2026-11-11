from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any


logger = logging.getLogger("migrations")


class MigrationRunner:
    """Manages forward-only schema migrations using SQLite PRAGMA user_version."""

    def __init__(self, db_path: Path, migrations_dir: Path | None = None) -> None:
        self.db_path = Path(db_path)
        if migrations_dir:
            self.migrations_dir = Path(migrations_dir)
        else:
            self.migrations_dir = self.db_path.parent / "migrations"

    def get_current_version(self, conn: sqlite3.Connection) -> int:
        row = conn.execute("PRAGMA user_version").fetchone()
        return row[0] if row else 0

    def set_version(self, conn: sqlite3.Connection, version: int) -> None:
        conn.execute(f"PRAGMA user_version = {int(version)}")

    def run_migrations(self) -> int:
        """Apply all pending migrations. Returns count of applied migrations."""
        if not self.migrations_dir.exists():
            return 0

        migration_files = sorted(self.migrations_dir.glob("*.sql"))
        if not migration_files:
            return 0

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        applied_count = 0

        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            current_ver = self.get_current_version(conn)

            for file in migration_files:
                # Expecting format 0001_name.sql
                parts = file.stem.split("_", 1)
                if not parts[0].isdigit():
                    continue
                file_ver = int(parts[0])

                if file_ver > current_ver:
                    logger.info("Applying database migration %04d: %s", file_ver, file.name)
                    sql_script = file.read_text(encoding="utf-8")
                    conn.executescript(sql_script)
                    self.set_version(conn, file_ver)
                    conn.commit()
                    current_ver = file_ver
                    applied_count += 1

        if applied_count > 0:
            logger.info("Successfully applied %d schema migrations (Current DB Version: %d)", applied_count, current_ver)
        return applied_count
