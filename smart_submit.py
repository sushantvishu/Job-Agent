"""
Smart submit script: reviews the queue, filters out junk, and submits real applications.
Delegates to the unified framework pipeline in app.pipeline.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.main import build_runtime
from app.pipeline import run_submission_batch

# Jobs that are clearly garbage — purge them without opening a browser
JUNK_PATTERNS = [
    r"linkedin\.com/company/",
    r"linkedin\.com/authwall",
    r"quickhyre\.ai/auth",
    r"fastforward\.career",
    r"linkedin\.com/feed",
    r"\?expJD=true",  # Naukri search results pages
]

# Titles that are clearly not cybersecurity / not relevant
JUNK_TITLES = [
    "join linkedin", "recruiter sign", "linkedin content", "feed detail",
    "tutelr", "welcome back", "isaca", "research associate",  # pharmaceutical research
    "clinical associate", "due diligence associate", "process associate",
    "associate cataloguer", "associate software tester", "career success associate",
    "chat support associate", "associate - airline", "associate - rtd",
    "walk-in || associate", "growth associate", "policy research associate",
    "research associates - fresher", "research associate",
]


def is_junk(url: str, title: str, score: int) -> tuple[bool, str]:
    url_lower = url.lower()
    title_lower = (title or "").lower()
    for pattern in JUNK_PATTERNS:
        if re.search(pattern, url_lower):
            return True, f"Junk URL pattern: {pattern}"
    for t in JUNK_TITLES:
        if t in title_lower and score < 60:
            return True, f"Low-score junk title: {title}"
    if "linkedin.com/jobs/view" in url_lower and (not title or title.strip() == ""):
        return True, "Blank-title LinkedIn job (likely login wall)"
    return False, ""


def main() -> None:
    print("=" * 60)
    print("SMART SUBMIT RUNNER — Reviewing and submitting queue")
    print("=" * 60)

    config, logger, tracker, profile, collector, matcher, filler, _ = build_runtime()
    filler.non_interactive = True

    stats = run_submission_batch(
        config=config,
        tracker=tracker,
        filler=filler,
        collector=collector,
        profile=profile,
        matcher=matcher,
        statuses=("filled_pending_submit",),
        limit=50,
        headless=False,
        auto_submit_safe=True,
        junk_url_checker=is_junk,
    )

    print()
    print("=" * 60)
    print(f"DONE! Submitted: {stats['submitted']} | Still Pending: {stats['still_pending']} | Skipped: {stats['skipped']} | Errors: {stats['errors']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
