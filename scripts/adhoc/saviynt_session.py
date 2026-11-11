from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.browser import BrowserSession
from app.config import load_config
from app.profile_loader import load_profile
from app.utils import setup_logger


URL = "https://jobs.lever.co/saviynt/92b766cd-d60f-4244-827d-7fc199cae6fc/apply"


def write_log(message: str) -> None:
    path = Path("logs/saviynt_session.log")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now().isoformat(timespec='seconds')} | {message}\n")


def fill(locator, value: str) -> None:
    if not value:
        return
    if locator.count():
        locator.first.fill(value)


def check(locator) -> None:
    if locator.count():
        try:
            locator.first.check()
        except Exception:
            locator.first.click()


def main() -> None:
    config = load_config()
    logger = setup_logger(config.log_path, config.log_level)
    profile = load_profile(config.profile_path)

    write_log("starting Saviynt-only session")
    with BrowserSession(config, logger, headless=False) as browser:
        page = browser.goto(URL)
        page.wait_for_timeout(8000)

        file_input = page.locator("input[type='file']")
        if file_input.count():
            file_input.first.set_input_files(str(config.resume_path))

        fill(page.locator("input[name='name']"), profile.name)
        check(page.locator("input[name='pronouns'][value='Use name only']"))
        fill(page.locator("input[name='email']"), profile.email)
        fill(page.locator("input[name='phone']"), profile.phone)
        fill(page.locator("input[name='location']"), profile.location)
        fill(page.locator("input[name='urls[GitHub]']"), profile.links.get("github", ""))
        fill(page.locator("input[name='urls[Portfolio]']"), profile.links.get("portfolio", ""))

        # Leave optional fields blank unless the profile explicitly contains them.
        fill(page.locator("input[name='urls[LinkedIn]']"), profile.links.get("linkedin", ""))
        fill(page.locator("input[name='org']"), "")
        fill(page.locator("input[name='urls[Twitter]']"), "")
        fill(page.locator("input[name='urls[Other]']"), "")

        write_log("Saviynt prefilled; hCaptcha/final submit remains manual")
        browser.wait_until_browser_closed()
    write_log("Saviynt-only session closed")


if __name__ == "__main__":
    main()
