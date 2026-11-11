"""
src/tracker.py — SQLite Job Tracker and Audit Log Manager.

Persists scraped jobs and application statuses into SQLite while isolating
all execution logs, CSV exports, and structured JSON audits into the /logs folder.
"""
from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.settings import settings
from database.init_db import db_manager

logger = logging.getLogger("src.tracker")


@dataclass
class JobRecord:
    source: str
    company: str
    title: str
    url: str
    canonical_key: str = ""
    location: str = ""
    score: int = 0
    status: str = "discovered"
    reason: str = ""
    red_flags: str = ""
    missing_skills: str = ""
    criteria_text: str = ""
    notes: str = ""
    applied_at: Optional[str] = None


class JobTracker:
    """Manages application records in SQLite and writes isolated logs to /logs."""

    def __init__(self) -> None:
        # Guarantee self-healing database is initialized
        db_manager.initialize_database()
        self.logs_dir = settings.logs_dir
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.csv_log_path = self.logs_dir / "scraped_jobs.csv"
        self.json_log_path = self.logs_dir / "scraped_jobs.jsonl"

    def record_job(self, job: JobRecord) -> int:
        """
        Saves or updates a job record in SQLite with conflict resolution,
        and appends audit entries to isolated log files.
        """
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO jobs (
                    source, company, title, url, canonical_key, location, score,
                    status, reason, red_flags, missing_skills, criteria_text, notes, applied_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
                ON CONFLICT(url) DO UPDATE SET
                    score = excluded.score,
                    status = CASE 
                        WHEN jobs.status = 'applied' THEN 'applied' 
                        ELSE excluded.status 
                    END,
                    reason = excluded.reason,
                    notes = excluded.notes,
                    updated_at = datetime('now', 'localtime');
                """,
                (
                    job.source,
                    job.company,
                    job.title,
                    job.url,
                    job.canonical_key,
                    job.location,
                    job.score,
                    job.status,
                    job.reason,
                    job.red_flags,
                    job.missing_skills,
                    job.criteria_text,
                    job.notes,
                    job.applied_at,
                ),
            )
            conn.commit()
            job_id = cursor.lastrowid or 0

        # Log into isolated CSV and JSONL files in /logs
        self._append_to_file_logs(job)
        return job_id

    def update_status(self, url: str, status: str, notes: str = "", applied: bool = False) -> None:
        """Updates status of a tracked job."""
        applied_at = datetime.now().isoformat() if applied else None
        with db_manager.get_connection() as conn:
            if applied_at:
                conn.execute(
                    "UPDATE jobs SET status = ?, notes = ?, applied_at = ?, updated_at = datetime('now', 'localtime') WHERE url = ?;",
                    (status, notes, applied_at, url),
                )
            else:
                conn.execute(
                    "UPDATE jobs SET status = ?, notes = ?, updated_at = datetime('now', 'localtime') WHERE url = ?;",
                    (status, notes, url),
                )
            conn.commit()
        logger.info("Updated job status: %s -> %s", url, status)

    def is_already_processed(self, canonical_key: str, url: str) -> bool:
        """Checks if a job has already been evaluated or applied."""
        with db_manager.get_connection() as conn:
            row = conn.execute(
                "SELECT id, status FROM jobs WHERE canonical_key = ? OR url = ? LIMIT 1;",
                (canonical_key, url),
            ).fetchone()
            if row:
                return row["status"] in ("applied", "skipped", "filled_pending_submit")
        return False

    def get_summary_stats(self) -> Dict[str, int]:
        """Returns aggregate application statistics."""
        with db_manager.get_connection() as conn:
            rows = conn.execute("SELECT status, COUNT(*) as c FROM jobs GROUP BY status;").fetchall()
            return {r["status"]: r["c"] for r in rows}

    def _append_to_file_logs(self, job: JobRecord) -> None:
        """Appends scraped job details to isolated text/JSON files in /logs."""
        try:
            # 1. JSON Lines Log
            with open(self.json_log_path, "a", encoding="utf-8") as f:
                record = asdict(job)
                record["logged_at"] = datetime.now().isoformat()
                f.write(json.dumps(record) + "\n")

            # 2. CSV Log
            file_exists = self.csv_log_path.exists() and self.csv_log_path.stat().st_size > 0
            with open(self.csv_log_path, "a", newline="", encoding="utf-8") as f:
                fieldnames = [
                    "timestamp", "source", "company", "title", "location",
                    "score", "status", "url", "reason"
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if not file_exists:
                    writer.writeheader()
                writer.writerow({
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "source": job.source,
                    "company": job.company,
                    "title": job.title,
                    "location": job.location,
                    "score": job.score,
                    "status": job.status,
                    "url": job.url,
                    "reason": job.reason,
                })
        except Exception as exc:
            logger.warning("Failed to write to isolated /logs files: %s", exc)


# Global tracker instance
tracker = JobTracker()
