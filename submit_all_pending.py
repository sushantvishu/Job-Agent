"""
submit_all_pending.py — Autonomous Submitter for Staged & Blocked Jobs.
Delegates to the unified framework pipeline in app.pipeline.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.main import build_runtime
from app.pipeline import run_submission_batch


def main() -> None:
    print("=" * 70)
    print("AUTONOMOUS ZERO-MANUAL-INPUT SUBMISSION ENGINE")
    print("Processing all 'needs_manual_input' and 'filled_pending_submit' jobs")
    print("=" * 70)

    config, logger, tracker, profile, collector, matcher, filler, _ = build_runtime()
    filler.non_interactive = True

    stats = run_submission_batch(
        config=config,
        tracker=tracker,
        filler=filler,
        collector=collector,
        profile=profile,
        matcher=matcher,
        statuses=("needs_manual_input", "filled_pending_submit"),
        limit=100,
        headless=False,
        auto_submit_safe=True,
        warm_up=True,
    )

    print("\n" + "=" * 70)
    print(f"RUN COMPLETE: {stats}")
    print("=" * 70)


if __name__ == "__main__":
    main()
