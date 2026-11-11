"""
login_linkedin.py — Quick 1-time LinkedIn Interactive Authenticator.
Run this once from your terminal to log in.
Once logged in, your session is saved permanently in browser-profile.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent
PROFILE_DIR = PROJECT_ROOT / "browser-profile"
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

print("=" * 72)
print("  🔐 LinkedIn 1-Time Session Login Setup")
print(f"  Target Profile: {PROFILE_DIR}")
print("=" * 72)

with sync_playwright() as p:
    print("Launching Chrome browser window...")
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        executable_path=CHROME_PATH if Path(CHROME_PATH).exists() else None,
        channel="chrome" if not Path(CHROME_PATH).exists() else None,
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
        viewport={"width": 1280, "height": 800},
    )

    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")

    print("\n👉 Please sign in to LinkedIn in the browser window.")
    print("   (Click 'Sign in with Google' or enter your LinkedIn email & password)")
    print("   Actively monitoring for login completion...")

    logged_in = False
    for sec in range(600):  # 10 minute window
        try:
            for p_open in ctx.pages:
                url = p_open.url.lower()
                if "feed" in url and "login" not in url and "authwall" not in url:
                    logged_in = True
                    break
        except Exception:
            pass

        if logged_in:
            print(f"\n✅ LinkedIn session verified successfully after {sec}s!")
            print("=" * 72)
            print("  🎉 AUTHENTICATION COMPLETE!")
            print(f"  Your session is permanently saved in: {PROFILE_DIR}")
            print("  You can now run the applier in full live capacity:")
            print("     python linkedin_post_applier.py --live --pages 10")
            print("=" * 72)
            time.sleep(3)
            break

        time.sleep(1)

    if not logged_in:
        print("\n❌ Login wait timed out after 10 minutes.")

    ctx.close()

