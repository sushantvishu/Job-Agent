"""
app/pipeline.py — Unified Scouting and Submission Execution Pipeline.

Consolidates the core loops for:
1. run_submission_batch: Autonomous submission of shortlisted/pending applications.
2. run_scout_cycle: Autonomous discovery, deduplication, and scoring of job postings.
"""
from __future__ import annotations

import logging
import random
import time
from typing import Any, Callable

from app.browser import BrowserSession
from app.config import AppConfig
from app.form_filler import FormFiller
from app.job_collector import JobCollector
from app.matcher import JobMatcher, MatchResult
from app.profile_loader import ProfileData
from app.tracker import JobTracker
from app.utils import JobPosting

logger = logging.getLogger("pipeline")


def warm_up_sessions(session: BrowserSession, logger: logging.Logger) -> None:
    """Warm up Naukri and LinkedIn sessions with saved persistent profile cookies."""
    for platform, url in (("Naukri", "https://www.naukri.com/"), ("LinkedIn", "https://www.linkedin.com/jobs/")):
        try:
            page = session.goto(url)
            page.wait_for_timeout(2000)
            logger.info("Session %s warm-up complete.", platform)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Session %s warm-up note: %s", platform, exc)


def run_submission_batch(
    config: AppConfig,
    tracker: JobTracker,
    filler: FormFiller,
    collector: JobCollector,
    profile: ProfileData,
    matcher: JobMatcher,
    statuses: tuple[str, ...] = ("filled_pending_submit", "shortlisted"),
    limit: int = 20,
    headless: bool = False,
    auto_submit_safe: bool = True,
    warm_up: bool = True,
    junk_url_checker: Callable[[str, str, int], tuple[bool, str]] | None = None,
) -> dict[str, int]:
    """
    Submits a batch of pending or shortlisted jobs with unified error handling and tracking.

    Returns summary stats dict: {"submitted": int, "still_pending": int, "skipped": int, "errors": int}
    """
    from app.main import detect_apply_path

    stats = {"submitted": 0, "still_pending": 0, "skipped": 0, "errors": 0}

    with tracker._connect() as conn:
        status_placeholders = ",".join("?" for _ in statuses)
        rows = conn.execute(
            f"SELECT * FROM jobs WHERE status IN ({status_placeholders}) ORDER BY score DESC LIMIT ?",
            (*statuses, limit),
        ).fetchall()

    if not rows:
        logger.info("No applications in queue for statuses: %s", statuses)
        return stats

    logger.info("Starting submission batch for %d jobs (headless=%s)", len(rows), headless)

    with BrowserSession(config, logger, headless=headless) as session:
        if warm_up:
            warm_up_sessions(session, logger)

        for idx, row in enumerate(rows, start=1):
            url = row["url"]
            title = row["title"] or "Unknown Role"
            company = row["company"] or "Unknown Company"
            score = row["score"] or 0

            # ── 1. Fast-Path Pre-Flight Gate (Prunes expired listings in 50ms) ──
            from app.preflight import PreFlightChecker
            is_active, preflight_reason = PreFlightChecker.check_url(url)
            if not is_active:
                logger.info("[%d/%d] Pre-flight pruned dead listing: %s (%s)", idx, len(rows), title, preflight_reason)
                job = JobPosting(url=url, source=row["source"], company=company, title=title)
                match = MatchResult(score=score, decision="skip", reasons=[preflight_reason])
                tracker.upsert_job(job, match, status="skipped", reason=f"Pre-flight: {preflight_reason}")
                stats["skipped"] += 1
                continue

            # ── 2. Walk-In Interview Notice Dispatcher ──
            from app.walkin import is_walkin_requisition, extract_walkin_details, emit_walkin_brief
            job = JobPosting(
                url=url,
                source=row["source"],
                company=company,
                title=title,
                description="",
                location=row["location"] if "location" in row.keys() else "",
            )
            match = MatchResult(
                score=score,
                decision="shortlist" if score >= 60 else "skip",
                reasons=[row["reason"] or "Batch submission"],
            )

            if is_walkin_requisition(title):
                logger.info("[%d/%d] Detected Walk-In Interview drive: %s @ %s", idx, len(rows), title, company)
                walkin_info = extract_walkin_details(job)
                emit_walkin_brief([walkin_info], config.project_root / "exports" / "walkin_interviews.md")
                tracker.upsert_job(job, match, status="walkin_extracted", reason=f"Walk-in drive: {walkin_info['interview_date']} | {walkin_info['venue'][:80]}")
                stats["skipped"] += 1
                continue

            # Filter out known junk URLs if checker provided
            if junk_url_checker:
                is_junk, junk_reason = junk_url_checker(url, title, score)
                if is_junk:
                    logger.info("[%d/%d] Skipping junk: %s (%s)", idx, len(rows), title, junk_reason)
                    tracker.upsert_job(job, match, status="skipped", reason=junk_reason)
                    stats["skipped"] += 1
                    continue

            logger.info("[%d/%d] [%d pts] Processing: %s @ %s", idx, len(rows), score, title, company)

            # Auto-submit requires score >= 60 to prevent auto-applying to low-quality drift
            can_auto_submit = auto_submit_safe and score >= 60

            try:
                with session.isolated_page() as page:
                    page.goto(url, wait_until="domcontentloaded", timeout=config.default_timeout_ms)
                    page.wait_for_timeout(2000)

                    apply_path = detect_apply_path(page)
                    if apply_path == "unsupported":
                        logger.warning("Unsupported platform redirect for %s", url)
                        tracker.upsert_job(job, match, status="skipped", reason="Unsupported application platform")
                        stats["skipped"] += 1
                        continue

                    fill_result, active_page = filler.fill(
                        page, job, match, profile, auto_submit_safe=can_auto_submit
                    )

                    if fill_result.status == "applied":
                        logger.info("✓ Successfully applied: %s @ %s", title, company)
                        tracker.upsert_job(job, match, status="applied", reason="Submitted via unified pipeline")
                        stats["submitted"] += 1
                    elif fill_result.status in ("filled_pending_submit", "needs_manual_input"):
                        if can_auto_submit:
                            sub_ok, msg = filler.submit_final(active_page, explicit_confirmation=False)
                            if sub_ok:
                                logger.info("✓ Final submit confirmed: %s @ %s", title, company)
                                tracker.upsert_job(job, match, status="applied", reason="Final submit confirmed")
                                stats["submitted"] += 1
                            else:
                                logger.info("Pending manual input (%s): %s", msg, url)
                                tracker.upsert_job(job, match, status=fill_result.status, reason=msg)
                                stats["still_pending"] += 1
                        else:
                            tracker.upsert_job(job, match, status=fill_result.status, reason=fill_result.reason or "Score below auto-submit floor; queued for review")
                            stats["still_pending"] += 1
                    else:
                        tracker.upsert_job(job, match, status=fill_result.status, reason=fill_result.reason)
                        stats["still_pending"] += 1

            except Exception as exc:  # noqa: BLE001
                logger.error("Error submitting %s: %s", url, exc)
                stats["errors"] += 1

            # Humanized randomized jitter
            time.sleep(random.uniform(1.2, 2.5))

    logger.info("Batch complete: %s", stats)
    return stats

