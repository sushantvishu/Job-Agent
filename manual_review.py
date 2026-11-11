import sqlite3
import time
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from app.main import build_runtime
from app.browser import BrowserSession

def main():
    print("==================================================")
    print("?? INTERACTIVE MANUAL REVIEW MODE")
    print("==================================================")
    
    config, logger, tracker, profile, _, _, filler, _ = build_runtime()
    
    c = sqlite3.connect('d:/job-agent/jobs.db')
    c.row_factory = sqlite3.Row
    
    # Target jobs sitting in the manual queue
    rows = c.execute("SELECT * FROM jobs WHERE status = 'filled_pending_submit'").fetchall()
    
    if not rows:
        print("Your manual submit queue is empty! Great job.")
        return
        
    print(f"Found {len(rows)} jobs waiting for you to click Submit.")
    print("The browser will open each page one by one. Once you submit the application, come back to this terminal and press ENTER to move to the next one.")
    input("\nPress ENTER to launch the browser and begin...")
    
    with BrowserSession(config, logger, headless=False) as session:
        for idx, row in enumerate(rows, 1):
            url = row["url"]
            print(f"\n[{idx}/{len(rows)}] Opening: {row['title']} at {row['company']}")
            
            try:
                page = session.goto(url)
                
                # We do not refill the form automatically because we don't want to overwrite what you might be editing,
                # but if the page is blank (e.g. redirected), we could trigger filler.fill(). 
                # For safety, we just give you the page as-is, which usually preserves state or requires a quick click.
                
                print(">>> Browser is open. Please review the application, solve any captchas, and click Submit.")
                user_input = input(">>> Type 'skip' to skip this job, or just press ENTER if you successfully submitted it: ").strip().lower()
                
                if user_input == 'skip':
                    print("Skipping job...")
                    continue
                
                # Mark as applied in the database
                c.execute("UPDATE jobs SET status = 'applied', reason = 'Manually reviewed and submitted by user.' WHERE url = ?", (url,))
                c.commit()
                print("? Marked as Successfully Applied in the database!")
                
                # Close any extra tabs opened during external navigation
                while len(session.context.pages) > 1:
                    session.context.pages[-1].close()
                    time.sleep(0.5)
                    
            except Exception as e:
                print(f"ERROR: {e}")
                
            time.sleep(1)
            
    print("\n?? You have reached the end of the queue!")

if __name__ == '__main__':
    main()
