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


URL = "https://alconcysec.zohorecruit.in/jobs/Careers/110562000001356041"
CURRENT_JOB_TITLE = "Technical Support Specialist"


def write_log(message: str) -> None:
    path = Path("logs/alcon_session.log")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now().isoformat(timespec='seconds')} | {message}\n")


def main() -> None:
    config = load_config()
    logger = setup_logger(config.log_path, config.log_level)
    profile = load_profile(config.profile_path)
    first_name, _, last_name = profile.name.partition(" ")
    last_name = last_name or first_name
    skills = ", ".join(profile.skills[:10])

    with BrowserSession(config, logger, headless=False) as browser:
        page = browser.goto(URL)
        page.wait_for_timeout(8000)
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
            12: "",
            13: "",
        }
        for index, value in values.items():
            try:
                if inputs.count() > index:
                    inputs.nth(index).fill(value)
            except Exception as exc:  # noqa: BLE001
                write_log(f"field {index} failed: {exc}")

        file_inputs = page.locator("input[type='file']")
        try:
            if file_inputs.count() >= 2:
                file_inputs.nth(1).set_input_files(str(config.resume_path))
            elif file_inputs.count() == 1:
                file_inputs.first.set_input_files(str(config.resume_path))
        except Exception as exc:  # noqa: BLE001
            write_log(f"resume upload failed: {exc}")

        write_log("Alcon prefilled; CAPTCHA/final submit remains manual")
        browser.wait_until_browser_closed()


if __name__ == "__main__":
    main()
