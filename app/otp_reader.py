from __future__ import annotations

import email
import imaplib
import re
import ssl
import time
from typing import Any


class OtpReader:
    """Reads a one-time password from the most recent unread email using IMAP."""

    def __init__(self, host: str, address: str, app_password: str, logger: Any) -> None:
        self.host = host
        self.address = address
        self.app_password = app_password
        self.logger = logger

    def fetch_latest_otp(self, wait_seconds: int = 30, poll_interval: int = 5) -> str:
        """Poll the inbox for up to `wait_seconds` and return the first OTP found."""
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            otp = self._scan_inbox()
            if otp:
                return otp
            time.sleep(poll_interval)
        self.logger.warning("OTP not found in inbox within %s seconds.", wait_seconds)
        return ""

    def _scan_inbox(self) -> str:
        try:
            ssl_context = ssl.create_default_context()
            with imaplib.IMAP4_SSL(self.host, ssl_context=ssl_context) as conn:
                conn.login(self.address, self.app_password)
                conn.select("INBOX")
                _, data = conn.search(None, "UNSEEN")
                mail_ids = data[0].split() if data and data[0] else []
                for mail_id in reversed(mail_ids[-5:]):
                    _, msg_data = conn.fetch(mail_id, "(RFC822)")
                    if not msg_data or not msg_data[0]:
                        continue
                    raw = msg_data[0][1]
                    msg = email.message_from_bytes(raw)
                    body = self._extract_body(msg)
                    otp = self._extract_otp(body)
                    if otp:
                        self.logger.info("OTP found in email: %s", otp)
                        return otp
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("OTP inbox scan failed: %s", exc)
        return ""

    @staticmethod
    def _extract_body(msg: email.message.Message) -> str:
        parts: list[str] = []
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                if ct in ("text/plain", "text/html"):
                    try:
                        parts.append(part.get_payload(decode=True).decode(errors="replace"))
                    except Exception:  # noqa: BLE001
                        pass
        else:
            try:
                parts.append(msg.get_payload(decode=True).decode(errors="replace"))
            except Exception:  # noqa: BLE001
                pass
        return " ".join(parts)

    @staticmethod
    def _extract_otp(text: str) -> str:
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
