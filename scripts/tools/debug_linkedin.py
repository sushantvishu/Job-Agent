import sqlite3
from playwright.sync_api import sync_playwright

def debug_linkedin():
    conn = sqlite3.connect('d:/job-agent/jobs.db')
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT url FROM jobs WHERE status='filled_pending_submit' AND source='linkedin' LIMIT 1").fetchone()
    if not row:
        print("No LinkedIn jobs found")
        return
    url = row["url"]
    print(f"Testing URL: {url}")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir="d:/job-agent/browser-profile",
            headless=False
        )
        page = context.new_page()
        page.goto(url)
        page.wait_for_timeout(3000)
        
        print(f"Final URL: {page.url}")
        print(f"Title: {page.title()}")
        page.screenshot(path="debug_linkedin.png")
        
        context.close()

if __name__ == "__main__":
    debug_linkedin()

