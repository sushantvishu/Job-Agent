"""
auto_apply_all.py — Bulk job application runner with graceful shutdown.
Delegates to the unified framework pipeline in app.pipeline.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

from app.main import build_runtime
from app.pipeline import run_submission_batch
from app.shutdown import ShutdownManager


def main() -> None:
    print("==================================================")
    print("🚀 INITIATING MASSIVE REGRESSION & APPLY RUN")
    print("==================================================")

    config, logger, tracker, profile, collector, matcher, filler, _ = build_runtime()
    filler.non_interactive = True

    # Register OS signal handlers
    sm = ShutdownManager(logger)
    sm.register()

    stats = run_submission_batch(
        config=config,
        tracker=tracker,
        filler=filler,
        collector=collector,
        profile=profile,
        matcher=matcher,
        statuses=("filled_pending_submit", "shortlisted"),
        limit=1000,
        headless=config.headless,
        auto_submit_safe=True,
        warm_up=True,
    )

    print("\n==================================================")
    print(f"MASSIVE APPLY RUN COMPLETE: {stats}")
    print("==================================================")


if __name__ == "__main__":
    main()
