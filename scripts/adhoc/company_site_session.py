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


CURRENT_JOB_TITLE = "Technical Support Specialist"


def write_log(message: str) -> None:
    path = Path("logs/company_site_session.log")
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{timestamp} | {message}\n")


def try_fill(locator, value: str) -> bool:
    if not value:
        return False
    try:
        if locator.count():
            locator.first.fill(value)
            return True
    except Exception as exc:  # noqa: BLE001
        write_log(f"fill failed: {exc}")
    return False


def try_check(locator) -> bool:
    try:
        if locator.count():
            locator.first.check()
            return True
    except Exception:
        try:
            locator.first.click()
            return True
        except Exception as exc:  # noqa: BLE001
            write_log(f"check failed: {exc}")
    return False


def try_upload(locator, resume_path: str) -> bool:
    try:
        if locator.count():
            locator.first.set_input_files(resume_path)
            return True
    except Exception as exc:  # noqa: BLE001
        write_log(f"upload failed: {exc}")
    return False


def fill_zoho(page, profile, resume_path: str) -> None:
    first_name, _, last_name = profile.name.partition(" ")
    last_name = last_name or first_name
    skills = ", ".join(profile.skills[:10])
    inputs = page.locator("input[type='text'], input[type='email'], input[type='tel'], textarea")
    values = {
        0: first_name,
        1: last_name,
        2: profile.email,
        4: profile.phone,
        5: "",
        6: "Bengaluru",
        7: "Karnataka",
        8: "",
        9: "India",
        10: CURRENT_JOB_TITLE,
        11: skills,
        12: profile.links.get("linkedin", ""),
        13: "",
    }
    for index, value in values.items():
        try:
            if inputs.count() > index and value:
                inputs.nth(index).fill(value)
        except Exception as exc:  # noqa: BLE001
            write_log(f"Zoho field {index} failed: {exc}")

    try_fill(page.locator("input[id*='LinkedIn' i], input[name*='LinkedIn' i]"), profile.links.get("linkedin", ""))
    file_inputs = page.locator("input[type='file']")
    try:
        if file_inputs.count() >= 2:
            file_inputs.nth(1).set_input_files(resume_path)
        elif file_inputs.count() == 1:
            file_inputs.first.set_input_files(resume_path)
    except Exception as exc:  # noqa: BLE001
        write_log(f"Zoho resume upload failed: {exc}")


def fill_lever(page, profile, resume_path: str) -> None:
    try_upload(page.locator("input[type='file']"), resume_path)
    try_fill(page.locator("input[name='name']"), profile.name)
    try_check(page.locator("input[name='pronouns'][value='Use name only']"))
    try_fill(page.locator("input[name='email']"), profile.email)
    try_fill(page.locator("input[name='phone']"), profile.phone)
    try_fill(page.locator("input[name='location']"), profile.location)
    try_fill(page.locator("input[name='org']"), CURRENT_JOB_TITLE)
    try_fill(page.locator("input[name='urls[LinkedIn]']"), profile.links.get("linkedin", ""))
    try_fill(page.locator("input[name='urls[GitHub]']"), profile.links.get("github", ""))
    try_fill(page.locator("input[name='urls[Portfolio]']"), profile.links.get("portfolio", ""))


def open_netrika(page) -> None:
    try:
        page.locator("#position").select_option(label="SOC Analyst")
        page.locator("#department").select_option(label="Cyber Security")
    except Exception as exc:  # noqa: BLE001
        write_log(f"Netrika filters failed: {exc}")


def main() -> None:
    config = load_config()
    logger = setup_logger(config.log_path, config.log_level)
    profile = load_profile(config.profile_path)
    resume_path = str(config.resume_path)

    targets = [
        ("Alcon SOC Analyst L1", "https://alconcysec.zohorecruit.in/jobs/Careers/110562000001356041", "zoho"),
        ("Saviynt SOC Analyst I", "https://jobs.lever.co/saviynt/92b766cd-d60f-4244-827d-7fc199cae6fc/apply", "lever"),
        ("Netrika Work With Us", "https://www.netrika.com/work-with-us/", "netrika"),
        ("Pragma Edge India Openings", "https://careers.pragmaedge.com/job-openings-india/", "review"),
    ]

    write_log("starting company-site session")
    with BrowserSession(config, logger, headless=False) as browser:
        for index, (name, url, kind) in enumerate(targets):
            if index == 0:
                page = browser.goto(url)
            else:
                page = browser.context.new_page()
                page.set_default_timeout(config.default_timeout_ms)
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
            write_log(f"opened {name}: {page.url}")
            page.wait_for_timeout(5000)
            if kind == "zoho":
                fill_zoho(page, profile, resume_path)
                write_log(f"prefilled {name}; CAPTCHA/final submit remains manual")
            elif kind == "lever":
                fill_lever(page, profile, resume_path)
                write_log(f"prefilled {name}; hCaptcha/final submit remains manual")
            elif kind == "netrika":
                open_netrika(page)
                write_log("opened Netrika with SOC/Cyber filters for manual job selection")
            else:
                write_log(f"opened {name} for manual review")

        write_log("company-site pages ready; waiting for browser close")
        browser.wait_until_browser_closed()
    write_log("company-site session closed")


if __name__ == "__main__":
    main()
