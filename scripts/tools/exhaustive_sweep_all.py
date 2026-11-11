"""
app/exhaustive_sweep_all.py — Autonomous orchestrator that runs sweeps
across ALL remaining unsearched keywords until complete, without stopping.
"""
from __future__ import annotations

import glob
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

# Ensure root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_config
from app.tracker import JobTracker
from app.profile_loader import load_profile
from app.main import build_search_keywords, prioritize_unsearched_keywords

logger = logging.getLogger("exhaustive_sweep")
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


def get_unsearched_keywords(cfg, tracker, profile) -> list[str]:
    all_kws = build_search_keywords(profile)
    seen_keys = tracker.get_seen_search_keys()
    prioritized = prioritize_unsearched_keywords(all_kws, tracker)
    unsearched = [
        kw for kw in all_kws
        if not any(w in s or s in w for s in seen_keys for w in [kw.lower()])
    ]
    return [kw for kw in prioritized if kw in unsearched]


def main() -> None:
    cfg = load_config()
    tracker = JobTracker(cfg.db_path, logger)
    profile = load_profile(cfg.profile_path)
    profile_dir = Path(cfg.browser_profile_dir)

    python_exe = sys.executable

    iteration = 1
    while True:
        stop_ollama()
        clean_locks(profile_dir)

        unsearched = get_unsearched_keywords(cfg, tracker, profile)
        print("\n" + "=" * 70)
        print(f"  EXHAUSTIVE SWEEP — BATCH {iteration}")
        print(f"  Remaining unsearched terms: {len(unsearched)}")
        print("=" * 70)

        if not unsearched:
            print("\n[SUCCESS] ALL search keywords have been exhaustively searched and processed!")
            break

        batch_kws = unsearched[:20]
        print(f"Current batch ({len(batch_kws)} terms):")
        for i, kw in enumerate(batch_kws, 1):
            print(f"  {i:2d}. {kw}")

        cmd = [
            python_exe,
            "app/main.py",
            "autorun",
            "--keyword-count", "20",
            "--max-per-search", "6",
            "--limit", "40",
            "--min-score", "50",
            "--apply-limit", "25",
            "--fresh-only",
            "--fresh-days", "14",
            "--no-linkedin-posts",
            "--linkedin-jobs",
            "--prioritize-unsearched",
        ]

        print(f"\n[Launching batch {iteration}...] Command: {' '.join(cmd)}")
        start_time = time.time()
        res = subprocess.run(cmd)
        duration = time.time() - start_time
        print(f"\n[Batch {iteration} finished in {duration:.1f}s | Exit code: {res.returncode}]")

        stop_ollama()
        clean_locks(profile_dir)
        iteration += 1
        time.sleep(5)

    print("\n" + "=" * 70)
    print("  ALL KEYWORD SWEEPS COMPLETE — EXECUTING FINAL VERIFICATION")
    print("=" * 70)


if __name__ == "__main__":
    main()

