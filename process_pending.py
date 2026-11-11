"""
process_pending.py — Processes pending and manual input jobs.
Delegates to the unified framework pipeline in app.pipeline.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.main import build_runtime
from app.pipeline import run_submission_batch


def main() -> None:
    print("=" * 60)
    print("PROCESSING ALL PENDING & MANUAL INPUT JOBS")
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
        statuses=("filled_pending_submit", "needs_manual_input"),
        limit=50,
        headless=False,
        auto_submit_safe=True,
        warm_up=True,
    )

    print("\n" + "=" * 60)
    print(f"PROCESSING COMPLETE: {stats}")
    print("=" * 60)


if __name__ == "__main__":
    main()
