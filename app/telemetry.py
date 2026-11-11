from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from app.tracker import JobTracker


logger = logging.getLogger("telemetry")


def log_event(event_name: str, logs_dir: Path | None = None, **metadata: Any) -> None:
    """Emit a structured JSONL event for analytics and observability."""
    try:
        target_dir = logs_dir or Path("logs")
        target_dir.mkdir(parents=True, exist_ok=True)
        event_path = target_dir / "events.jsonl"
        
        record = {
            "timestamp": datetime.now().isoformat(),
            "event": event_name,
            **metadata,
        }
        with event_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Telemetry event logging failed: %s", exc)


def calculate_funnel_metrics(tracker: JobTracker) -> dict[str, Any]:
    """Calculate the complete job application conversion funnel metrics from SQLite."""
    with tracker._connect() as conn:
        # Total counts by status
        status_rows = conn.execute("SELECT status, count(*) FROM jobs GROUP BY status").fetchall()
        status_counts = {r[0]: r[1] for r in status_rows}

        # Source breakdown
        source_rows = conn.execute("SELECT source, count(*) FROM jobs GROUP BY source").fetchall()
        source_counts = {r[0]: r[1] for r in source_rows}

        # Recruiter outreach emails
        try:
            post_rows = conn.execute("SELECT status, count(*) FROM linkedin_post_emails GROUP BY status").fetchall()
            post_counts = {r[0]: r[1] for r in post_rows}
        except Exception:
            post_counts = {}

    total_jobs = sum(status_counts.values())
    applied = status_counts.get("applied", 0)
    shortlisted = status_counts.get("shortlisted", 0)
    filled_pending = status_counts.get("filled_pending_submit", 0)
    needs_manual = status_counts.get("needs_manual_input", 0)
    skipped = status_counts.get("skipped", 0)
    failed = status_counts.get("failed", 0)

    # Conversion rate calculation
    actionable_pool = applied + shortlisted + filled_pending + needs_manual
    conversion_rate = (applied / actionable_pool * 100.0) if actionable_pool > 0 else 0.0

    return {
        "timestamp": datetime.now().isoformat(),
        "total_jobs_tracked": total_jobs,
        "funnel": {
            "scouted_total": total_jobs,
            "shortlisted": shortlisted,
            "filled_pending_submit": filled_pending,
            "needs_manual_input": needs_manual,
            "applied": applied,
            "skipped": skipped,
            "failed": failed,
            "conversion_rate_percent": round(conversion_rate, 2),
        },
        "platforms": source_counts,
        "recruiter_outreach": {
            "emails_sent": post_counts.get("sent", 0),
            "dry_runs": post_counts.get("dry_run", 0),
        },
    }
