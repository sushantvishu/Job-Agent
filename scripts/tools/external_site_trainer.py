import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from app.utils import MatchResult, JobPosting
from app.form_filler import FormFiller
from app.main import build_runtime, detect_apply_path
from app.browser import BrowserSession

def main():
    config, logger, tracker, profile, collector, matcher, filler, _ = build_runtime()
    
    # Get all skipped company websites
    jobs = tracker.list_jobs(limit=100)
    company_jobs = [j for j in jobs if j.get('status') == 'skipped' and 'Company website' in str(j.get('reason'))]
    
    if not company_jobs:
        print("No external company jobs left to train on!")
        return
        
    target = company_jobs[0]
    url = target['url']
    
    print(f"\n==============================================")
    print(f"TRAINING ON EXTERNAL SITE: {target.get('title')} at {target.get('company')}")
    print(f"URL: {url}")
    print(f"==============================================\n")

    with BrowserSession(config, logger, headless=False) as browser:
        try:
            page = browser.goto(url)
            job = collector.collect(page, url)
            if not job.title and target.get("title"): job.title = target["title"]
            if not job.company and target.get("company"): job.company = target["company"]
            match = matcher.score(job)
            
            # Step 1: Emulate clicking 'Apply on Company Website'
            filler.non_interactive = True 
            fill_result, application_page = filler.fill(
                page=page,
                job=job,
                match=match,
                profile=profile,
                auto_submit_safe=False
            )
            
            print(f"\n--- FILL RESULT ---")
            print(f"Status: {fill_result.status}")
            print(f"Errors: {fill_result.errors}")
            print(f"Blockers: {fill_result.submit_blockers}")
            print(f"Unknowns: {fill_result.unknown_questions}")
            
            if fill_result.status != "applied" and fill_result.status != "filled_pending_submit":
                success = False
            elif "filled" in str(fill_result.status) and "naukri.com" in application_page.url:
                print("\n[!] BOT CLAIMED SUCCESS BUT NEVER LEFT NAUKRI. False positive suspected.")
                success = False
            else:
                success = True
                
            if not success:
                print("\n[!] BOT FAILED TO NAVIGATE/FILL. Agent intervention required.")
                html = application_page.content()
                with open("failed_page_dump.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"Dumped page HTML to failed_page_dump.html. URL at end: {application_page.url}")
            else:
                print("\n[+] SUCCESS! Bot navigated and filled this variant correctly.")
                tracker.upsert_job(job, match, status="training_passed", reason="Handled external site correctly")

            time.sleep(3)
            
        except Exception as e:
            print(f"CRITICAL ERROR processing {url}: {e}")
        finally:
            try:
                browser.close_extra_tabs()
            except:
                pass

if __name__ == "__main__":
    main()
