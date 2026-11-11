from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.main import build_runtime, print_match_summary


def write_log(message: str) -> None:
    path = Path("logs/firefox_one_job_session.log")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now().isoformat(timespec='seconds')} | {message}\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    args = parser.parse_args()

    config, logger, tracker, profile, collector, matcher, filler, _ = build_runtime()
    profile_dir = config.project_root / "browser-profile-firefox"
    profile_dir.mkdir(parents=True, exist_ok=True)

    # Do not block a background process waiting for hidden stdin.
    filler._prompt_unknown_answer = lambda label, store_answer: ""  # noqa: SLF001

    with sync_playwright() as playwright:
        context = playwright.firefox.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            accept_downloads=True,
            viewport={"width": 1440, "height": 960},
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(config.default_timeout_ms)
        page.goto(args.url, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        job = collector.collect(page, args.url)
        match = matcher.score(job)
        print_match_summary(job, match)
        write_log(f"opened {job.title} | {job.company} | score={match.score} | {job.url}")

        if match.score < 50 or match.decision == "skip":
            tracker.upsert_job(job, match, status="skipped", reason=match.decision)
            write_log("skipped by score")
        else:
            fill_result, _application_page = filler.fill(
                page=page,
                job=job,
                match=match,
                profile=profile,
                auto_submit_safe=False,
            )
            reason_parts = fill_result.submit_blockers + fill_result.unknown_questions + fill_result.errors
            status = "needs_manual_input" if reason_parts else "filled_pending_submit"
            tracker.upsert_job(job, match, status=status, reason=", ".join(reason_parts[:4]))
            write_log(f"filled status={status} reason={'; '.join(reason_parts[:4])}")

        write_log("waiting for manual browser review")
        while True:
            try:
                if not [item for item in context.pages if not item.is_closed()]:
                    break
            except Exception:
                break
            time.sleep(1)
        context.close()


if __name__ == "__main__":
    main()
