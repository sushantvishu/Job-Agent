"""
src/browser.py — Portable Cross-Platform Selenium WebDriver Manager.

Automatically provisions and configures Chrome and Firefox WebDrivers across
Windows, macOS, and Linux using webdriver-manager with stealth anti-detection flags.
"""
from __future__ import annotations

import logging
import os
import platform
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService

# Add root directory to path if executed standalone
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config.settings import settings

logger = logging.getLogger("src.browser")


def get_chrome_options(headless: bool = False, user_agent: str | None = None) -> ChromeOptions:
    """Configures high-stealth Chrome options across operating systems."""
    options = ChromeOptions()
    if headless:
        # Modern headless mode
        options.add_argument("--headless=new")

    # Anti-bot and stealth flags
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f"--user-agent={user_agent or settings.user_agent}")

    # Exclude automation switches
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)
    
    # Disable password-save and autofill popups
    prefs = {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
        "profile.default_content_setting_values.notifications": 2,
    }
    options.add_experimental_option("prefs", prefs)
    return options


def get_firefox_options(headless: bool = False, user_agent: str | None = None) -> FirefoxOptions:
    """Configures high-stealth Firefox options across operating systems."""
    options = FirefoxOptions()
    if headless:
        options.add_argument("-headless")

    options.set_preference("dom.webdriver.enabled", False)
    options.set_preference("useAutomationExtension", False)
    options.set_preference("general.useragent.override", user_agent or settings.user_agent)
    options.set_preference("permissions.default.desktop-notification", 2)
    return options


def create_driver(
    browser_type: str | None = None,
    headless: bool | None = None,
    user_agent: str | None = None,
) -> webdriver.Remote:
    """
    Factory creating a fully portable WebDriver instance.
    Uses webdriver-manager to auto-download and link binaries on Windows/Mac/Linux.
    Falls back gracefully to system PATH if webdriver-manager is offline or unavailable.
    """
    target_browser = (browser_type or settings.browser_type).lower()
    is_headless = settings.headless if headless is None else headless
    ua = user_agent or settings.user_agent

    logger.info("Initializing portable WebDriver: [%s] (headless=%s, OS=%s)", target_browser, is_headless, platform.system())

    if target_browser in ("firefox", "gecko"):
        options = get_firefox_options(headless=is_headless, user_agent=ua)
        try:
            from webdriver_manager.firefox import GeckoDriverManager
            service = FirefoxService(GeckoDriverManager().install())
            driver = webdriver.Firefox(service=service, options=options)
        except Exception as exc:
            logger.warning("GeckoDriverManager failed (%s). Attempting system geckodriver fallback...", exc)
            driver = webdriver.Firefox(options=options)
        return driver

    # Default to Chrome
    options = get_chrome_options(headless=is_headless, user_agent=ua)
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    except Exception as exc:
        logger.warning("ChromeDriverManager failed (%s). Attempting system chromedriver fallback...", exc)
        driver = webdriver.Chrome(options=options)

    # Inject CDP stealth overrides to mask navigator.webdriver
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                window.chrome = {
                    runtime: {}
                };
                """
            },
        )
    except Exception as cdp_err:
        logger.debug("CDP stealth script injection note: %s", cdp_err)

    driver.set_page_load_timeout(settings.browser_timeout)
    return driver


@contextmanager
def get_browser(
    browser_type: str | None = None,
    headless: bool | None = None,
) -> Generator[webdriver.Remote, None, None]:
    """Context manager for safe browser session lifecycle management."""
    driver = create_driver(browser_type=browser_type, headless=headless)
    try:
        yield driver
    finally:
        try:
            driver.quit()
        except Exception as exc:
            logger.debug("Error shutting down browser driver: %s", exc)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Testing portable browser initialization...")
    with get_browser(headless=True) as d:
        d.get("https://httpbin.org/headers")
        print(f"Title: {d.title}")
        print(f"Page Source snippet: {d.page_source[:200]}")
    print("Browser test passed successfully.")
