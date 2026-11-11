"""
batch_submit_pending.py — Autonomous Review and Submission of Staged Applications
Delegates to the unified framework pipeline in app.pipeline.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import build_runtime
from app.pipeline import run_submission_batch

JUNK_URL_PATTERNS = [
    r"\?expJD=true",
    r"/authwall",
    r"/careers$",
    r"/vacancies$",
    r"placero\.in/jobs/data-engineer-medpace",
]


def is_unsubmittable_entry(url: str, title: str, score: int) -> tuple[bool, str]:
    url_lower = url.lower()
    title_lower = (title or "").lower()
    for pattern in JUNK_URL_PATTERNS:
        if re.search(pattern, url_lower):
            return True, f"Junk URL pattern: {pattern}"
    if "accenture" in (title_lower + url_lower) and score < 45:
        return True, "Irrelevant legacy Accenture duplicate (score < 45)"
    return False, ""


def main() -> None:
    print("=" * 70)
    print("AUTONOMOUS REVIEW & BATCH SUBMISSION OF STAGED APPLICATIONS")
    print("=" * 70)

    config, app_logger, tracker, profile, collector, matcher, filler, _ = build_runtime()
    filler.non_interactive = True

    stats = run_submission_batch(
        config=config,
        tracker=tracker,
        filler=filler,
        collector=collector,
        profile=profile,
        matcher=matcher,
        statuses=("filled_pending_submit",),
        limit=100,
        headless=True,
        auto_submit_safe=True,
        warm_up=True,
        junk_url_checker=is_unsubmittable_entry,
    )

    print("\n" + "=" * 70)
    print(f"REVIEW & SUBMISSION RUN COMPLETE: {stats}")
    print("=" * 70)


if __name__ == "__main__":
    main()
