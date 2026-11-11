"""
Unit tests for JobTracker SQLite operations, indexes, and concurrency.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.tracker import JobTracker
from app.utils import JobPosting, MatchResult


def test_tracker_lifecycle_and_indexes(tmp_path: Path):
    db_file = tmp_path / "test_jobs.db"
    tracker = JobTracker(db_file)
    tracker.init_db()

    with tracker._connect() as conn:
        indexes = [idx[1] for idx in conn.execute("PRAGMA index_list(jobs)").fetchall()]
        assert "idx_jobs_status" in indexes
        assert "idx_jobs_score" in indexes
        assert "idx_jobs_created_at" in indexes
        assert "idx_jobs_canonical_key" in indexes
        assert "idx_jobs_location" in indexes

        # Verify WAL mode
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert journal_mode.upper() == "WAL"

    job = JobPosting(
        url="https://example.com/job/test-1",
        source="linkedin",
        company="CyberTech",
        title="VAPT Analyst",
        description="OWASP testing",
        location="Bengaluru",
    )
    match = MatchResult(
        score=85,
        decision="strong apply",
        reasons=["Direct title match", "OWASP skill match"],
        matched_skills=["VAPT", "OWASP"],
    )

    # Insert job
    tracker.upsert_job(job, match, status="shortlisted")

    # Query job
    shortlisted = tracker.list_jobs(status="shortlisted")
    assert len(shortlisted) == 1
    assert shortlisted[0]["company"] == "CyberTech"
    assert shortlisted[0]["score"] == 85

    # Update job status
    tracker.upsert_job(job, match, status="applied", reason="Submitted via Chrome")
    applied = tracker.list_jobs(status="applied")
    assert len(applied) == 1
    assert applied[0]["reason"] == "Submitted via Chrome"

    # Status counts
    counts = tracker.stats()
    assert counts.get("applied") == 1
    assert counts.get("shortlisted", 0) == 0

    # Test database backup
    backup_file = tracker.backup_database(backup_dir=tmp_path / "backups")
    assert backup_file.exists()
    assert backup_file.stat().st_size > 0


if __name__ == "__main__":
    import tempfile
    import shutil
    temp_dir = Path(tempfile.mkdtemp())
    try:
        print("=" * 60)
        print("  RUNNING JOB TRACKER UNIT TESTS")
        print("=" * 60)
        test_tracker_lifecycle_and_indexes(temp_dir)
        print("✅ test_tracker_lifecycle_and_indexes PASSED")
        print("=" * 60)
        print("  🎉 ALL JOB TRACKER TESTS PASSED FLAWLESSLY!")
        print("=" * 60)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
