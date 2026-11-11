import sqlite3
from pathlib import Path
from app.migrations import MigrationRunner


def test_migration_runner(tmp_path: Path):
    db_file = tmp_path / "test_migration.db"
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()

    # Create dummy migration 1
    (migrations_dir / "0001_initial.sql").write_text(
        "CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT);",
        encoding="utf-8"
    )
    # Create dummy migration 2
    (migrations_dir / "0002_add_index.sql").write_text(
        "CREATE INDEX idx_test_name ON test_table(name);",
        encoding="utf-8"
    )

    runner = MigrationRunner(db_file, migrations_dir=migrations_dir)
    applied = runner.run_migrations()
    assert applied == 2

    with sqlite3.connect(db_file) as conn:
        ver = runner.get_current_version(conn)
        assert ver == 2
        # Verify table exists
        cols = [c[1] for c in conn.execute("PRAGMA table_info(test_table)").fetchall()]
        assert "name" in cols
        # Verify index exists
        indexes = [i[1] for i in conn.execute("PRAGMA index_list(test_table)").fetchall()]
        assert "idx_test_name" in indexes

    # Re-running applies 0 new migrations (idempotent)
    applied_again = runner.run_migrations()
    assert applied_again == 0
