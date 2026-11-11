"""
Targeted inspector for the 15 direct candidate jobs that had 'No final submit button was found'.
"""
import logging
from pathlib import Path
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("inspector")

TARGET_IDS = [1902, 1946, 2064, 1862, 1944, 1875, 2037, 1852, 2036, 1879, 1998, 1866, 1938, 1987]

import sqlite3
conn = sqlite3.connect('d:/job-agent/jobs.db')
c = conn.cursor()
c.execute(f"SELECT id, title, company, url FROM jobs WHERE id IN ({','.join(map(str, TARGET_IDS))})")
jobs = c.fetchall()

print(f"Testing {len(jobs)} jobs...")

with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        user_data_dir=r"d:\job-agent\browser-profile",
        headless=True,
        viewport={"width": 1440, "height": 960},
    )
    browser.set_default_timeout(10000)
    browser.set_default_navigation_timeout(15000)

    for j_id, title, company, url in jobs:
        print(f"\n--- [ID {j_id}] {title} @ {company} ---")
        page = browser.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(2000)
            print("URL reached:", page.url)
            body = (page.inner_text("body") or "").lower()
            if "already applied" in body or "applied on" in body:
                print(">> ALREADY APPLIED on page!")
                c.execute("UPDATE jobs SET status = 'applied', reason = 'already applied on site' WHERE id = ?", (j_id,))
                conn.commit()
                continue

            # Look for apply button
            apply_btn = page.locator("#company-site-button, .company-site-button, #apply-button, .apply-button, button:has-text('Apply'), a:has-text('Apply')")
            print("Apply locators found:", apply_btn.count())
            for i in range(min(3, apply_btn.count())):
                b = apply_btn.nth(i)
                txt = (b.inner_text() or "").strip()
                tag = b.evaluate("el => el.tagName")
                print(f"  Button {i}: <{tag}> '{txt}' id={b.get_attribute('id')} class={b.get_attribute('class')}")
        except Exception as e:
            print("Error visiting:", e)
        finally:
            page.close()

    browser.close()
conn.close()

