import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from app.utils import MatchResult, JobPosting
from app.form_filler import FormFiller
from app.main import build_runtime, detect_apply_path

def main():
    config, logger, tracker, profile, collector, matcher, filler, _ = build_runtime()
    
    # Get shortlisted jobs (limit to 15 for this review session so it doesn't take forever)
    shortlisted = tracker.list_jobs(limit=15, status="shortlisted")
    if not shortlisted:
        print("No shortlisted jobs to process.")
        return

    from app.browser import BrowserSession
    with BrowserSession(config, logger, headless=False) as browser:
        for row in shortlisted:
            url = row['url']
            print(f"\n==============================================")
            print(f"REVIEWING JOB: {row.get('title')} at {row.get('company')}")
            print(f"URL: {url}")
            print(f"==============================================\n")
            
            try:
                page = browser.goto(url)
                job = collector.collect(page, url)
                if not job.title and row.get("title"): job.title = row["title"]
                if not job.company and row.get("company"): job.company = row["company"]
                match = matcher.score(job)
                
                apply_path = detect_apply_path(page)
                if apply_path == 'company website':
                    print("COMPANY WEBSITE DETECTED - Skipping as requested.")
                    tracker.upsert_job(job, match, status="filled_pending_submit", reason="Company website - skipping for later")
                    continue
                
                # Fill the form, but in interactive mode so it pauses at the end
                filler.non_interactive = False 
                fill_result, application_page = filler.fill(
                    page=page,
                    job=job,
                    match=match,
                    profile=profile,
                    auto_submit_safe=False
                )
                
                if fill_result.status == "needs_manual_input":
                    print(f"BLOCKED by: {', '.join(fill_result.submit_blockers or fill_result.unknown_questions)}")
                    print("Skipping to next job...")
                    tracker.upsert_job(job, match, status="needs_manual_input", reason="Blocked during review")
                    continue
                
                # It should now be paused at the decision prompt internally by filler.fill
                # But wait, filler.fill returns the result, it doesn't prompt!
                # Wait, filler.fill doesn't prompt. `main.py fill_and_review` does the prompt.
                
                # Let's write our own prompt that the AI can read.
                print(">>> READY FOR AGENT REVIEW <<<")
                if fill_result.guessed_fields:
                    print(f"Questions answered automatically: {fill_result.guessed_fields}")
                print("AGENT_ACTION_REQUIRED: Please review the application.")
                print("Type 'y' to submit, 'n' to skip, or 'save' to save for later.")
                
                decision = input("AGENT_PROMPT [y/n/save]: ").strip().lower()
                
                if decision == 'y':
                    print("Submitting...")
                    submitted, msg = filler.submit_final(application_page, explicit_confirmation=True)
                    if submitted:
                        tracker.upsert_job(job, match, status="applied", reason="Agent approved and submitted")
                        print("SUCCESSFULLY SUBMITTED!")
                    else:
                        print(f"Failed to submit: {msg}")
                elif decision == 'save':
                    tracker.upsert_job(job, match, status="filled_pending_submit", reason="Agent saved for later")
                    print("Saved for later.")
                else:
                    tracker.upsert_job(job, match, status="skipped", reason="Agent rejected application")
                    print("Skipped.")
                
            except Exception as e:
                print(f"Error processing {url}: {e}")
            finally:
                try:
                    browser.close_extra_tabs()
                except:
                    pass

if __name__ == "__main__":
    main()
