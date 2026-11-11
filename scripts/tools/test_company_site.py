import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from app.utils import MatchResult, JobPosting
from app.form_filler import FormFiller
from app.main import build_runtime, detect_apply_path

def main():
    config, logger, tracker, profile, collector, matcher, filler, _ = build_runtime()
    
    # Grab one company website job
    jobs = tracker.list_jobs(limit=100)
    company_jobs = [j for j in jobs if "Company website" in str(j.get('reason'))]
    if not company_jobs:
        print("No company website jobs found in tracker!")
        return
        
    target = company_jobs[0]
    url = target['url']
    
    print(f"\n==============================================")
    print(f"TESTING EXTERNAL SITE FLOW: {target.get('title')} at {target.get('company')}")
    print(f"URL: {url}")
    print(f"==============================================\n")

    from app.browser import BrowserSession
    with BrowserSession(config, logger, headless=False) as browser:
        try:
            page = browser.goto(url)
            job = collector.collect(page, url)
            if not job.title and target.get("title"): job.title = target["title"]
            if not job.company and target.get("company"): job.company = target["company"]
            match = matcher.score(job)
            
            # Instead of skipping, we let filler.fill do its magic
            # filler._ensure_application_form_open will click the apply button
            filler.non_interactive = True 
            fill_result, application_page = filler.fill(
                page=page,
                job=job,
                match=match,
                profile=profile,
                auto_submit_safe=False # Just fill, don't submit yet
            )
            
            print(f"\nResult: {fill_result.status}")
            print(f"Unknown questions: {fill_result.unknown_questions}")
            print(f"Errors: {fill_result.errors}")
            
            # Leave browser open for a few seconds to inspect
            time.sleep(10)
            
        except Exception as e:
            print(f"Error processing {url}: {e}")
        finally:
            try:
                browser.close_extra_tabs()
            except:
                pass

if __name__ == "__main__":
    main()
