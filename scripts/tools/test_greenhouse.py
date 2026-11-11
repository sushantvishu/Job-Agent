import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from app.utils import MatchResult, JobPosting
from app.main import build_runtime
from app.browser import BrowserSession

def main():
    config, logger, tracker, profile, collector, matcher, filler, exporter = build_runtime()
    filler.non_interactive = True

    # Use a real Greenhouse job from DB
    url = "https://job-boards.greenhouse.io/rockstargames/jobs/7827686003?gh_src=grb9z5wa3us"
    print(f"\nTesting external ATS (Greenhouse) with all fixes applied:")
    print(f"URL: {url}\n")

    job = JobPosting(url=url, source="greenhouse", company="Rockstar Games", title="Security/IT Role", description="")
    match = MatchResult(score=95, decision="shortlist", reasoning="Testing", match_types=[])

    with BrowserSession(config, logger, headless=True) as session:
        page = session.goto(url)
        print("Page loaded. Running FormFiller with CAPTCHA bypass + ATS adapters...")

        result, active_page = filler.fill(page, job, match, profile, auto_submit_safe=False)

        print("\n========== LIVE TEST RESULTS ==========")
        print(f"Status        : {result.status}")
        print(f"Filled Fields : {len(result.filled_fields)}")
        print(f"Errors        : {len(result.errors)}")
        print(f"Skipped       : {len(result.skipped_fields)}")

        if result.filled_fields:
            print("\nSuccessfully Filled:")
            for f in result.filled_fields:
                # strip huge strings for readability
                print(f"  ✓ {str(f)[:80]}")

        if result.errors:
            print("\nErrors Encountered:")
            for e in result.errors:
                msg = str(e)[:200]
                print(f"  ✗ {msg}")
        else:
            print("\nZERO ERRORS - Clean run!")

        print("=======================================\n")

if __name__ == "__main__":
    main()

