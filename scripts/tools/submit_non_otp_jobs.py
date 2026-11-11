"""
app/submit_non_otp_jobs.py — Submits all pending/staged job applications
where mobile OTP is NOT required, skipping any that require mobile OTP.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Ensure root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.browser import BrowserSession
from app.config import load_config
from app.job_collector import JobCollector
from app.matcher import JobMatcher, MatchResult
from app.utils import JobPosting
from app.profile_loader import load_profile, load_answer_templates
from app.tracker import JobTracker
from app.form_filler import FormFiller
from app.main import build_runtime, detect_apply_path

logger = logging.getLogger("submit_non_otp")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


def clean_locks(profile_dir: Path) -> None:
    """Purge stale Singleton lockfiles."""
    if profile_dir.is_dir():
        for lock in profile_dir.glob("Singleton*"):
            try:
                lock.unlink()
                logger.info("Purged stale lockfile: %s", lock.name)
            except Exception:
                pass


def stop_ollama() -> None:
    """Force terminate ollama.exe to release RAM."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/IM", "ollama.exe"], capture_output=True, timeout=5)
        else:
            subprocess.run(["pkill", "-f", "ollama serve"], capture_output=True, timeout=5)
    except Exception:
        pass


def is_mobile_otp_required(text: str) -> bool:
    """Check if page or dialog text explicitly asks for mobile/SMS OTP."""
    lower = text.lower()
    otp_indicators = [
        "enter mobile otp",
        "mobile otp",
        "sms otp",
        "otp sent to your mobile",
        "otp sent to your phone",
        "verify mobile number",
        "verify your phone",
        "phone verification code",
        "enter the otp sent to",
        "6 digit otp",
        "4 digit otp",
    ]
    return any(indicator in lower for indicator in otp_indicators)


def main() -> None:
    config, _, tracker, profile, collector, matcher, filler, _ = build_runtime()
    profile_dir = Path(config.browser_profile_dir)

    clean_locks(profile_dir)
    stop_ollama()

    # Query all eligible staged and pending jobs
    with tracker._connect() as conn:
        cursor = conn.cursor()
        # 1. First priority: filled_pending_submit
        cursor.execute("""
            SELECT id, source, title, company, score, url, status, reason
            FROM jobs
            WHERE status = 'filled_pending_submit'
            ORDER BY score DESC
        """)
        staged_rows = [dict(zip([col[0] for col in cursor.description], row)) for row in cursor.fetchall()]

        # 2. Second priority: needs_manual_input where score >= 50 and not already an OTP failure
        cursor.execute("""
            SELECT id, source, title, company, score, url, status, reason
            FROM jobs
            WHERE status = 'needs_manual_input'
              AND score >= 50
              AND reason NOT LIKE '%OTP%'
              AND reason NOT LIKE '%Verification Gate%'
            ORDER BY score DESC
        """)
        manual_rows = [dict(zip([col[0] for col in cursor.description], row)) for row in cursor.fetchall()]

    candidate_queue = staged_rows + manual_rows
    total_candidates = len(candidate_queue)

    print("=" * 75)
    print(f"  NON-OTP SUBMISSION SWEEP — {total_candidates} CANDIDATES QUEUED")
    print(f"  - Staged pending submit: {len(staged_rows)}")
    print(f"  - Manual pending (score >= 50, non-OTP): {len(manual_rows)}")
    print("=" * 75)

    submitted_count = 0
    skipped_otp_count = 0
    failed_count = 0

    with BrowserSession(config, logger, headless=True) as browser:
        for index, row in enumerate(candidate_queue, start=1):
            url = row["url"]
            title = row.get("title") or "Unknown"
            company = row.get("company") or "Unknown"
            score = int(row.get("score") or 0)
            source = row.get("source") or "unknown"

            print(f"\n[{index}/{total_candidates}] Processing: {title} @ {company} (Score: {score} | {source})")
            logger.info("URL: %s", url)

            try:
                page = browser.current_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)

                # Check if already applied on page
                body_text = page.inner_text("body").lower() if hasattr(page, "inner_text") else ""
                if "already applied" in body_text or "applied on" in body_text:
                    logger.info("Page indicates already applied — marking as applied.")
                    job = JobPosting(source=source, url=url, title=title, company=company)
                    match = MatchResult(score=score, decision="already applied")
                    tracker.upsert_job(job, match, status="applied", reason="already applied on site")
                    submitted_count += 1
                    continue

                # Pre-check for Mobile OTP on landing page
                if is_mobile_otp_required(body_text):
                    logger.warning("[SKIPPED - MOBILE OTP REQUIRED] %s @ %s", title, company)
                    job = JobPosting(source=source, url=url, title=title, company=company)
                    match = MatchResult(score=score, decision="mobile otp gate")
                    tracker.upsert_job(job, match, status="needs_manual_input", reason="Mobile/SMS OTP required")
                    skipped_otp_count += 1
                    continue

                # Run FormFiller
                job = collector.collect(page, url)
                match = matcher.score(job)
                match.score = max(match.score, score)

                fill_result, active_page = filler.fill(
                    page=page,
                    job=job,
                    match=match,
                    profile=profile,
                    auto_submit_safe=True,
                )

                # Post-fill check for Mobile OTP gate
                active_text = active_page.inner_text("body").lower() if hasattr(active_page, "inner_text") else ""
                if is_mobile_otp_required(active_text) or any("mobile/sms otp" in b.lower() for b in fill_result.submit_blockers):
                    logger.warning("[SKIPPED - MOBILE OTP REQUIRED] After form fill: %s @ %s", title, company)
                    tracker.upsert_job(job, match, status="needs_manual_input", reason="Mobile/SMS OTP required")
                    skipped_otp_count += 1
                    continue

                if fill_result.status == "applied":
                    logger.info("[SUCCESS - APPLIED] %s @ %s", title, company)
                    reason = "auto-submit-safe" if fill_result.auto_submitted else "applied on job board"
                    tracker.upsert_job(job, match, status="applied", reason=reason)
                    submitted_count += 1
                elif fill_result.ready_to_submit or not fill_result.submit_blockers:
                    # Attempt final submission if form is ready
                    submitted, message = filler.submit_final(active_page, explicit_confirmation=False)
                    if submitted:
                        logger.info("[SUCCESS - SUBMITTED FINAL] %s @ %s: %s", title, company, message)
                        tracker.upsert_job(job, match, status="applied", reason="submitted: no mobile OTP required")
                        submitted_count += 1
                    else:
                        logger.warning("Submission did not complete for %s @ %s: %s", title, company, message)
                        tracker.upsert_job(job, match, status="filled_pending_submit", reason=message)
                        failed_count += 1
                else:
                    blockers = ", ".join(fill_result.submit_blockers or fill_result.errors)
                    logger.warning("Job halted at gate: %s @ %s — %s", title, company, blockers)
                    tracker.upsert_job(job, match, status=fill_result.status, reason=blockers)
                    failed_count += 1

            except Exception as exc:
                logger.error("Error processing %s (%s): %s", title, url, exc)
                failed_count += 1
            finally:
                try:
                    browser.close_extra_tabs()
                except Exception:
                    pass

    stop_ollama()
    clean_locks(profile_dir)

    print("\n" + "=" * 75)
    print("  NON-OTP SUBMISSION SWEEP COMPLETE")
    print(f"  - Successfully Submitted: {submitted_count}")
    print(f"  - Skipped (Mobile OTP Required): {skipped_otp_count}")
    print(f"  - Remaining / Staged / Failed: {failed_count}")
    print("=" * 75)


if __name__ == "__main__":
    main()
