import re
import time
from typing import Any
from playwright.sync_api import BrowserContext, Page

class WebmailOtpReader:
    """DEPRECATED: Browser-based webmail scraping is disabled for account security.

    Navigating to Gmail/Outlook inside automated Playwright sessions risks account
    suspension and flags bot detection on the user's primary identity.
    Use app.otp_reader.OtpReader (IMAP SSL with App Password) instead.
    """

    def __init__(self, context: BrowserContext, logger: Any, provider: str = "gmail") -> None:
        self.context = context
        self.logger = logger
        self.provider = provider.lower()

    def fetch_latest_otp(self, wait_seconds: int = 60, poll_interval: int = 5) -> str:
        """Disabled for account security. Use OtpReader (IMAP) instead."""
        self.logger.warning(
            "WebmailOtpReader is disabled to protect your Google/Outlook account from bot bans. "
            "Use IMAP OtpReader with an App Password instead."
        )
        return ""

    def _fetch_from_gmail(self, page: Page, wait_seconds: int, poll_interval: int) -> str:
        page.goto("https://mail.google.com/mail/u/0/#inbox")
        
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            try:
                page.reload()
                page.wait_for_load_state("networkidle", timeout=10000)
                
                # 'zE' is the class Gmail uses for unread email rows
                unread_emails = page.locator("tr.zE")
                if unread_emails.count() > 0:
                    for i in range(min(3, unread_emails.count())):
                        row = unread_emails.nth(i)
                        row.click()
                        page.wait_for_timeout(2000)
                        
                        # Extract body text ('a3s' is the class for email body payload)
                        body = page.locator("div.a3s").first
                        if body.is_visible():
                            text = body.inner_text()
                            otp = self._extract_otp(text)
                            if otp:
                                self.logger.info("Successfully extracted OTP from Gmail: %s", otp)
                                return otp
                        
                        # Go back to inbox to check others
                        page.goto("https://mail.google.com/mail/u/0/#inbox")
                        page.wait_for_load_state("networkidle")
            except Exception as e:
                self.logger.debug("Error during Gmail poll loop: %s", e)
                
            time.sleep(poll_interval)
            
        self.logger.warning("No OTP found in Gmail within %s seconds.", wait_seconds)
        return ""

    def _fetch_from_outlook(self, page: Page, wait_seconds: int, poll_interval: int) -> str:
        page.goto("https://outlook.live.com/mail/0/inbox")
        
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            try:
                page.reload()
                page.wait_for_load_state("networkidle", timeout=10000)
                
                # Outlook unread messages usually have aria-label containing "Unread"
                unread_emails = page.locator("[aria-label*='Unread']")
                if unread_emails.count() > 0:
                    for i in range(min(3, unread_emails.count())):
                        row = unread_emails.nth(i)
                        row.click()
                        page.wait_for_timeout(2000)
                        
                        # ReadingPane is standard for Outlook web body
                        body = page.locator("[aria-label='Reading Pane']").first
                        if body.is_visible():
                            text = body.inner_text()
                            otp = self._extract_otp(text)
                            if otp:
                                self.logger.info("Successfully extracted OTP from Outlook: %s", otp)
                                return otp
                                
                        page.goto("https://outlook.live.com/mail/0/inbox")
                        page.wait_for_load_state("networkidle")
            except Exception as e:
                self.logger.debug("Error during Outlook poll loop: %s", e)
                
            time.sleep(poll_interval)
            
        self.logger.warning("No OTP found in Outlook within %s seconds.", wait_seconds)
        return ""

    @staticmethod
    def _extract_otp(text: str) -> str:
        # Match standard OTP patterns (4-8 digits near keyword, or fallback to isolated 6/4 digits)
        patterns = [
            r"\b(?:OTP|otp|code|pin|passcode|verification code)[^\d]{0,20}(\d{4,8})\b",
            r"\b(\d{6})\b",
            r"\b(\d{4})\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return ""

