"""
app/link_checker.py — Fast job expiry checker (HTTP only, no browser needed).

Checks jobs in non-final statuses (shortlisted, needs_manual_input,
filled_pending_submit) to see if they are still active. Expired/removed
jobs are marked as 'failed' so the apply runner skips them.

Detection methods per platform:
  Naukri   — redirect to ?expJD=true, HTTP 404, expiry text in HTML
  LinkedIn — redirect away from /jobs/view/, 404, "no longer accepting", etc.
  External — 404, connection error, generic expiry keywords

Run standalone:
    python -m app.link_checker            # check all non-final statuses
    python -m app.link_checker --status shortlisted --limit 200
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import requests

# --- Constants ----------------------------------------------------------------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

EXPIRY_SIGNALS = [
    # Naukri
    "job you are looking for is expired",
    "this job is no longer available",
    "job is no longer accepting",
    "position has been filled",
    "job has been closed",
    "job has expired",
    "listing has expired",
    "no longer available",
    # LinkedIn
    "no longer accepting applications",
    "job is closed",
    "this job is closed",
    "application deadline has passed",
    "this listing has been removed",
    "page not found",
    # Generic
    "404 - not found",
    "404 not found",
    "this page doesn't exist",
    "page does not exist",
]

ACTIVE_SIGNALS = [
    # Naukri
    "apply now",
    "apply on company site",
    "naukri-apply",
    # LinkedIn
    "easy apply",
    "apply on company website",
    "linkedin.com/jobs/view",
    # Generic
    "submit application",
    "apply for this job",
]

# Statuses to check (non-final, non-applied)
CHECK_STATUSES = ("shortlisted", "needs_manual_input", "filled_pending_submit")


# --- Core checker function ---------------------------------------------------

def check_url(url: str, timeout: int = 12) -> tuple[str, str]:
    """Return (status, reason) where status is 'active', 'expired', or 'error'."""
    url_lower = url.lower()
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        final_url = resp.url.lower()
        body_sample = resp.text.lower()[:8000]

        # --- Naukri-specific: redirect adds ?expJD=true
        if "expjd=true" in final_url:
            return "expired", "Naukri redirect: expJD=true"

        # --- LinkedIn: redirected away from /jobs/view/ (ignore authwall/login/signup)
        if "linkedin.com/jobs/view" in url_lower and "linkedin.com/jobs/view" not in final_url:
            if any(marker in final_url for marker in ("authwall", "login", "signup", "checkpoint")):
                return "active", "LinkedIn authwall (requires logged-in browser session)"
            return "expired", f"LinkedIn redirected away from job view: {final_url[:80]}"

        # --- HTTP 404
        if resp.status_code == 404:
            return "expired", "HTTP 404 Not Found"

        # --- HTTP 4xx/5xx (not 401/403 which may be auth walls, not expiry)
        if resp.status_code in (410,):
            return "expired", f"HTTP {resp.status_code} Gone"

        # --- Expiry text signals
        for signal in EXPIRY_SIGNALS:
            if signal in body_sample:
                return "expired", f"Text signal: '{signal[:60]}'"

        # --- Active signals (confirm still live)
        for signal in ACTIVE_SIGNALS:
            if signal in body_sample:
                return "active", f"Active signal found: '{signal}'"

        # --- Default: ambiguous but not definitively expired
        return "active", f"HTTP {resp.status_code}, no expiry signals"

    except requests.exceptions.ConnectionError:
        return "expired", "Connection error (domain may be gone)"
    except requests.exceptions.Timeout:
        return "error", "Request timed out"
    except Exception as exc:  # noqa: BLE001
        return "error", str(exc)[:80]


# --- Main checker -----------------------------------------------------------

def run_check(
    db_path: str,
    statuses: tuple[str, ...] = CHECK_STATUSES,
    limit: int = 5000,
    delay: float = 0.4,
    logger=None,
) -> dict[str, Any]:
    """Check all jobs in the given statuses and update the DB.

    Returns a summary dict: {active, expired, error, total}.
    """
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row

    placeholders = ",".join("?" for _ in statuses)
    rows = conn.execute(
        f"SELECT id, url, title, company, source, status, score FROM jobs "
        f"WHERE status IN ({placeholders}) ORDER BY score DESC, id DESC LIMIT ?",
        (*statuses, limit),
    ).fetchall()

    total = len(rows)
    counts: dict[str, int] = {"active": 0, "expired": 0, "error": 0}

    _print(f"\n{'='*60}")
    _print(f"Job Expiry Check — {total} jobs to verify")
    _print(f"Statuses: {', '.join(statuses)}")
    _print(f"{'='*60}\n")

    expired_rows: list[sqlite3.Row] = []
    error_rows: list[sqlite3.Row] = []

    for idx, row in enumerate(rows, 1):
        url = row["url"]
        title = (row["title"] or "Unknown")[:50]
        company = (row["company"] or "Unknown")[:28]
        source = row["source"] or "?"
        score = row["score"] or 0

        _print(f"[{idx:03}/{total}] [{source}] {title} @ {company} (score={score})")

        result, reason = check_url(url)
        counts[result] = counts.get(result, 0) + 1

        if result == "expired":
            _print(f"         -> EXPIRED: {reason}")
            expired_rows.append(row)
            conn.execute(
                "UPDATE jobs SET status='failed', reason=? WHERE id=?",
                (f"Link check: expired — {reason}", row["id"]),
            )
        elif result == "error":
            _print(f"         -> ERROR  : {reason} (keeping in queue)")
            error_rows.append(row)
            # Don't update status for transient errors — keep in queue
        else:
            _print(f"         -> ACTIVE")

        # Commit in batches of 25 to minimise data loss on crash
        if idx % 25 == 0:
            conn.commit()

        time.sleep(delay)

    conn.commit()
    conn.close()

    # --- Final report
    _print(f"\n{'='*60}")
    _print(f"Link Check Complete")
    _print(f"  Active  : {counts['active']}")
    _print(f"  Expired : {counts['expired']}  <- marked as 'failed' in DB")
    _print(f"  Error   : {counts['error']}   <- left in queue (transient)")
    _print(f"  Total   : {total}")
    _print(f"{'='*60}\n")

    return {"active": counts["active"], "expired": counts["expired"],
            "error": counts["error"], "total": total}


def _print(msg: str) -> None:
    print(msg, flush=True)


# --- CLI entry point ---------------------------------------------------------

if __name__ == "__main__":
    import argparse

    from app.config import load_config

    default_db = str(load_config().db_path)
    parser = argparse.ArgumentParser(description="Check job link expiry and discard dead listings.")
    parser.add_argument("--db", default=default_db, help="Path to jobs.db")
    parser.add_argument(
        "--status",
        nargs="+",
        default=list(CHECK_STATUSES),
        choices=list(CHECK_STATUSES) + ["all"],
        help="Which statuses to check (default: all non-final)",
    )
    parser.add_argument("--limit", type=int, default=5000, help="Max rows to check")
    parser.add_argument("--delay", type=float, default=0.4, help="Seconds between requests")
    args = parser.parse_args()

    statuses = tuple(CHECK_STATUSES if "all" in args.status else args.status)
    run_check(db_path=args.db, statuses=statuses, limit=args.limit, delay=args.delay)

