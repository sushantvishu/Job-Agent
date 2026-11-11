from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        help="URL to open. Repeat for multiple tabs.",
    )
    args = parser.parse_args()

    config = load_config()
    profile_dir = config.project_root / "browser-profile-firefox"
    profile_dir.mkdir(parents=True, exist_ok=True)
    targets = args.url or ["https://www.naukri.com/", "https://www.linkedin.com/jobs/"]

    with sync_playwright() as playwright:
        context = playwright.firefox.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            accept_downloads=True,
            viewport={"width": 1440, "height": 960},
        )
        for index, url in enumerate(targets):
            page = context.pages[0] if index == 0 and context.pages else context.new_page()
            page.set_default_timeout(config.default_timeout_ms)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)

        while True:
            try:
                if not [page for page in context.pages if not page.is_closed()]:
                    break
            except Exception:
                break
            time.sleep(1)
        context.close()


if __name__ == "__main__":
    main()
