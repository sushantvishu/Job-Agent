import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from app.utils import MatchResult, JobPosting
from app.form_filler import FormFiller
from app.main import build_runtime, detect_apply_path

def main():
    config, logger, tracker, profile, collector, matcher, filler, _ = build_runtime()
    
    # We want to process jobs that were left as filled_pending_submit
    pending = tracker.list_jobs(limit=52, status="filled_pending_submit")
    if not pending:
        print("No pending jobs to submit!")
        return

    from app.browser import BrowserSession
    with BrowserSession(config, logger, headless=False) as browser:
        for row in pending:
            url = row['url']
            print(f"\n==============================================")
            print(f"MASS SUBMITTING JOB: {row.get('title')} at {row.get('company')}")
            print(f"==============================================\n")
            
            try:
                page = browser.goto(url)
                job = collector.collect(page, url)
                if not job.title and row.get("title"): job.title = row["title"]
                if not job.company and row.get("company"): job.company = row["company"]
                match = matcher.score(job)
                
                apply_path = detect_apply_path(page)
                if apply_path == 'company website':
                    tracker.upsert_job(job, match, status="skipped", reason="Company website redirect")
                    continue
                
                # Fill the form and forcefully submit
                filler.non_interactive = True 
                fill_result, application_page = filler.fill(
                    page=page,
                    job=job,
                    match=match,
                    profile=profile,
                    auto_submit_safe=True
                )
                
                # Force the submit button click since it's already vetted
                if fill_result.ready_to_submit or fill_result.auto_submitted:
                    print("Clicking Final Submit!")
                    submitted, msg = filler.submit_final(application_page, explicit_confirmation=False)
                    if submitted:
                        print("SUCCESSFULLY SUBMITTED!")
                        tracker.upsert_job(job, match, status="applied", reason="Mass bulk submission completed")
                    else:
                        print(f"Submit failed: {msg}")
                        tracker.upsert_job(job, match, status="needs_manual_input", reason=msg)
                else:
                    print(f"Skipping because not ready: block={fill_result.submit_blockers}")
                
            except Exception as e:
                print(f"Error processing {url}: {e}")
            finally:
                try:
                    browser.close_extra_tabs()
                except:
                    pass

if __name__ == "__main__":
    main()
