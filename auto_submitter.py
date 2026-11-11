"""
auto_submitter.py — Auto-submitter for shortlisted applications.
Delegates to the unified framework pipeline in app.pipeline.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.main import build_runtime
from app.pipeline import run_submission_batch


def main() -> None:
    print("=" * 60)
    print("AUTO SUBMITTER — Submitting shortlisted applications")
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
        statuses=("shortlisted",),
        limit=72,
        headless=False,
        auto_submit_safe=True,
    )

    print()
    print("=" * 60)
    print(f"DONE! Submitted: {stats['submitted']} | Still Pending: {stats['still_pending']} | Skipped: {stats['skipped']} | Errors: {stats['errors']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
