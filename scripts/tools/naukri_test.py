"""
Test: Open a real Naukri job page with the logged-in profile and verify
1. The 'read more' button is found and clicked
2. The job description text is extracted
"""
import sys, time
sys.path.insert(0, 'd:/job-agent')
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from app.job_collector import JobCollector
from app.config import load_config
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger('test')

config = load_config()

JOB_URL = "https://www.naukri.com/job-listings-vapt-engineer-innspark-solutions-faradabad-1-to-3-years-160926032961"
SEARCH_URL = "https://www.naukri.com/vapt-jobs-in-india?k=vapt&l=india&experience=0"

collector = JobCollector(logger)

with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        user_data_dir=str(config.browser_profile_dir),
        headless=False,
        executable_path=config.browser_executable_path or None,
        args=['--no-sandbox'],
    )
    page = browser.pages[0] if browser.pages else browser.new_page()

    # Test 1: Search page URL collection
    print("\n=== TEST 1: Naukri Search Page URL Collection ===")
    page.goto(SEARCH_URL, wait_until='domcontentloaded')
    page.wait_for_timeout(4000)
    candidates = collector._extract_naukri_listing_candidates(page, ['vapt', 'security'], 5)
    print(f"Found {len(candidates)} job candidates:")
    for c in candidates:
        print(f"  - {c.get('title', '?')} @ {c.get('company', '?')} => {c.get('url', '?')[:80]}")

    # Test 2: Job page description expansion
    print("\n=== TEST 2: Job Page Description Expansion ===")
    page.goto(JOB_URL, wait_until='domcontentloaded')
    page.wait_for_timeout(3000)
    before = len(page.locator('body').inner_text())
    print(f"Text length before expansion: {before}")

    n_clicks = collector._expand_naukri_description(page)
    print(f"Naukri 'read more' clicks: {n_clicks}")

    page.wait_for_timeout(1500)
    after = len(page.locator('body').inner_text())
    print(f"Text length after expansion: {after}")
    print(f"Text delta: {after - before}")

    # Extract description
    soup = BeautifulSoup(page.content(), 'lxml')
    desc_el = soup.select_one("section[class*='job-desc']") or soup.select_one("div[class*='dang-inner-html']")
    if desc_el:
        desc_text = desc_el.get_text(' ', strip=True)
        print(f"\nDescription length: {len(desc_text)}")
        print(f"Description preview: {desc_text[:300]}")
    else:
        print("WARNING: No job description section found on page!")
        # Show all sections found
        for sec in soup.find_all('section')[:5]:
            print(f"  section class: {sec.get('class')}")

    browser.close()

print("\nTest complete.")
