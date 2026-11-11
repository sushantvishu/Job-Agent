import sqlite3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from app.utils import MatchResult, JobPosting
from app.form_filler import FormFiller
from app.main import build_runtime, detect_apply_path
from app.browser import BrowserSession

def test_linkedin():
    print("Testing LinkedIn Auto-Apply...")
    config, logger, tracker, profile, collector, matcher, filler, exporter = build_runtime()
    filler.non_interactive = True
    
    # Get one LinkedIn job
    with tracker._connect() as c:
        row = c.execute("SELECT * FROM jobs WHERE source='linkedin' AND status IN ('shortlisted', 'filled_pending_submit') ORDER BY score DESC LIMIT 1").fetchone()
    
    if not row:
        print("No LinkedIn jobs found in queue.")
        return
        
    url = row["url"]
    print(f"Testing URL: {url}")
    
    job = JobPosting(url=url, source=row["source"], company=row["company"], title=row["title"], description="", location=row["location"] if "location" in row.keys() else "")
    match = MatchResult(score=row["score"] or 0, decision="shortlist", reasons=[row["reason"] or ""])
    
    with BrowserSession(config, logger, headless=False) as session:
        page = session.goto(url)
        apply_path = detect_apply_path(page)
        
        fill_result, active_page = filler.fill(page, job, match, profile, auto_submit_safe=False)
        print(f"Fill Status: {fill_result.status}")
        
        if fill_result.status == "filled_pending_submit":
            print("Attempting final submit...")
            submitted, msg = filler.submit_final(active_page, explicit_confirmation=False)
            print(f"Submitted: {submitted}, Msg: {msg}")
            
if __name__ == "__main__":
    test_linkedin()
