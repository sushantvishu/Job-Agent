from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.browser import BrowserSession
from app.main import build_runtime, print_match_summary


def write_log(message: str) -> None:
    path = Path("logs/one_job_session.log")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now().isoformat(timespec='seconds')} | {message}\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    args = parser.parse_args()

    config, logger, tracker, profile, collector, matcher, filler, _ = build_runtime()

    # Do not block a background process waiting for hidden stdin.
    filler._prompt_unknown_answer = lambda label, store_answer: ""  # noqa: SLF001

    with BrowserSession(config, logger, headless=False) as browser:
        page = browser.goto(args.url)
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
        browser.wait_until_browser_closed()


if __name__ == "__main__":
    main()
