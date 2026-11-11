"""SMS OTP reader — reads OTP codes from Android SMS via Windows Phone Link (YourPhone) SQLite DB.

Strategy 1 (primary): Query the Phone Link `phone.db` `message` table.
  - DB location: %LOCALAPPDATA%\\Packages\\Microsoft.YourPhone_8wekyb3d8bbwe\\LocalCache\\Indexed\\<GUID>\\System\\Database\\phone.db
  - Opens in read-only URI mode to avoid locking issues with the live app.

Strategy 2 (fallback): ADB over USB/WiFi (if adb.exe is on PATH).
  - Runs: adb shell content query --uri content://sms/inbox ...
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import time
import logging

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

OTP_PATTERN = re.compile(r"\b(\d{4,8})\b")

# Keywords that indicate a message likely contains an OTP
OTP_CONTEXT_KEYWORDS = (
    "otp",
    "one time password",
    "one-time",
    "verification code",
    "verify",
    "login code",
    "auth code",
    "passcode",
    "access code",
    "secret code",
    "security code",
    "your code",
    "code is",
    "code:",
)

# Keywords that indicate financial / banking transaction SMS — MUST NEVER be treated as job OTPs
BANKING_TRANSACTION_KEYWORDS = (
    "debited",
    "credited",
    "credit card",
    "debit card",
    "bank",
    "txn",
    "transaction",
    "spent",
    "transfer",
    "upi",
    "rs.",
    "inr",
    "atm",
    "account balance",
    "wallet",
    "netbanking",
    "card ending",
)

# Safe keywords that confirm the SMS is hiring/recruitment related
JOB_OR_AUTH_ALLOW_KEYWORDS = (
    "naukri",
    "linkedin",
    "job",
    "career",
    "apply",
    "applicant",
    "hiring",
    "recruitment",
    "portal",
    "lever",
    "greenhouse",
    "workday",
    "smartrecruiters",
)

def _is_otp_message(body: str) -> bool:
    """Return True if the message body looks like it contains a job application OTP."""
    lower = body.lower()
    # Reject financial transactions immediately to avoid ever leaking banking 2FA
    if any(bkw in lower for bkw in BANKING_TRANSACTION_KEYWORDS):
        if not any(jkw in lower for jkw in JOB_OR_AUTH_ALLOW_KEYWORDS):
            return False
    return any(kw in lower for kw in OTP_CONTEXT_KEYWORDS)


def _extract_otp(body: str) -> str | None:
    """Extract the most likely OTP digit string from a message body."""
    if not _is_otp_message(body):
        return None

    # Priority 1: Direct contextual regex patterns (highest precision)
    direct_patterns = [
        r"(?:otp|code|verification\s*code|pin|passcode)\s*(?:is|:|-|\.|\s)?\s*(\d{4,8})\b",
        r"\b(\d{4,8})\s*(?:is\s*(?:the|your)\s*(?:one-time|otp|code|verification))",
        r"\b(\d{4,8})\s*(?:is\s*your\s*security\s*code)",
    ]
    for pat in direct_patterns:
        m = re.search(pat, body, re.IGNORECASE)
        if m:
            return m.group(1)

    matches = OTP_PATTERN.findall(body)
    if not matches:
        return None
    # Prefer 6-digit codes (standard Indian telecom & banking OTP length)
    for m in matches:
        if len(m) == 6:
            return m
    # Accept 4–8 digit codes
    for m in matches:
        if 4 <= len(m) <= 8:
            return m
    return None


# --------------------------------------------------------------------------- #
# Phone Link DB path discovery
# --------------------------------------------------------------------------- #

def _find_phone_link_dbs() -> list[str]:
    """Return all discovered paths to Phone Link phone.db files across all user profiles/GUIDs."""
    localappdata = os.environ.get("LOCALAPPDATA", "")
    if not localappdata:
        return []
    pattern = os.path.join(
        localappdata,
        "Packages",
        "Microsoft.YourPhone_8wekyb3d8bbwe",
        "LocalCache",
        "Indexed",
        "*",
        "System",
        "Database",
        "phone.db",
    )
    return glob.glob(pattern)


def _find_phone_link_db() -> str | None:
    """Return path to the most recent Phone Link phone.db or None if not found."""
    dbs = _find_phone_link_dbs()
    if not dbs:
        return None
    # Pick the most recently modified database (checking both DB and WAL)
    def _recency(p: str) -> float:
        wal = p + "-wal"
        m = os.path.getmtime(p)
        if os.path.exists(wal):
            m = max(m, os.path.getmtime(wal))
        return m

    return max(dbs, key=_recency)


# --------------------------------------------------------------------------- #
# Strategy 1 — Phone Link SQLite
# --------------------------------------------------------------------------- #

def _read_otp_from_phone_link(since_epoch_ms: int, logger: logging.Logger) -> str | None:
    """Query all Phone Link message tables for a recent OTP SMS."""
    try:
        import sqlite3
    except ImportError:
        return None

    db_paths = _find_phone_link_dbs()
    if not db_paths:
        logger.debug("[SMS-OTP] No Phone Link DB paths found.")
        return None

    all_rows: list[tuple[str, int]] = []
    # Convert since_epoch_ms (Unix ms) to Windows FILETIME:
    # FILETIME = (unix_epoch_seconds + 11644473600) * 10_000_000
    filetime_since = (since_epoch_ms / 1000 + 11_644_473_600) * 10_000_000

    for db_path in db_paths:
        try:
            # Open read-only to avoid locking the live app
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3)
            c = conn.cursor()
            c.execute(
                "SELECT body, timestamp FROM message WHERE type in (1, 0) AND timestamp >= ? ORDER BY timestamp DESC LIMIT 50",
                (int(filetime_since),),
            )
            rows = c.fetchall()
            conn.close()
            all_rows.extend(rows)
        except Exception as e:
            logger.debug("[SMS-OTP] Phone Link DB (%s) read notice: %s", db_path, e)

    # Sort newest first across all connected devices
    all_rows.sort(key=lambda r: r[1], reverse=True)

    for body, ts in all_rows:
        if not body:
            continue
        otp = _extract_otp(body)
        if otp:
            logger.info("[SMS-OTP] Found OTP %s in SMS: %s", otp, body[:80])
            return otp

    return None


# --------------------------------------------------------------------------- #
# Strategy 2 — ADB fallback
# --------------------------------------------------------------------------- #

def _read_otp_from_adb(since_epoch_ms: int, logger: logging.Logger) -> str | None:
    """Read recent SMS via adb and extract OTP."""
    try:
        result = subprocess.run(
            [
                "adb", "shell", "content", "query",
                "--uri", "content://sms/inbox",
                "--where", f"date>{since_epoch_ms}",
                "--sort", "date DESC",
                "--projection", "body",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            logger.debug("[SMS-OTP] adb returned non-zero: %s", result.stderr.strip())
            return None
        for line in result.stdout.splitlines():
            if "body=" in line:
                body = line.split("body=", 1)[1]
                otp = _extract_otp(body)
                if otp:
                    logger.info("[SMS-OTP] ADB found OTP %s in: %s", otp, body[:80])
                    return otp
    except FileNotFoundError:
        logger.debug("[SMS-OTP] adb not found on PATH.")
    except subprocess.TimeoutExpired:
        logger.warning("[SMS-OTP] adb timed out.")
    except Exception as e:
        logger.warning("[SMS-OTP] ADB error: %s", e)
    return None


# --------------------------------------------------------------------------- #
# Public interface
# --------------------------------------------------------------------------- #

class SmsOtpReader:
    """Read SMS OTP codes from an Android phone connected via Windows Phone Link or ADB."""

    def __init__(self, logger: logging.Logger | None = None):
        self.logger = logger or logging.getLogger(__name__)

    def fetch_latest_otp(
        self,
        wait_seconds: int = 45,
        poll_interval: int = 5,
        lookback_seconds: int = 60,
    ) -> str | None:
        """Wait up to *wait_seconds* for a new OTP SMS and return the code.

        Looks back *lookback_seconds* to catch OTPs that arrived just before polling began.
        Polls Phone Link DB and ADB every *poll_interval* seconds.
        Returns None if no OTP is found within the timeout.
        """
        db_path = _find_phone_link_db()
        if not db_path:
            self.logger.warning(
                "[SMS-OTP] Windows Phone Link database not found. Ensure 'Link to Windows' is installed and paired."
            )

        start_time = time.time()
        since_epoch_ms = int((start_time - lookback_seconds) * 1000)
        deadline = start_time + wait_seconds

        self.logger.info(
            "[SMS-OTP] Polling for SMS OTP (timeout=%ds, lookback=%ds, since_epoch_ms=%d)...",
            wait_seconds,
            lookback_seconds,
            since_epoch_ms,
        )

        while time.time() < deadline:
            # Strategy 1: Phone Link SQLite DB
            otp = _read_otp_from_phone_link(since_epoch_ms, self.logger)
            if otp:
                return otp
            # Strategy 2: ADB fallback
            otp = _read_otp_from_adb(since_epoch_ms, self.logger)
            if otp:
                return otp
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            self.logger.debug(
                "[SMS-OTP] No OTP detected yet, retrying in %ds (%ds remaining)...",
                poll_interval,
                int(remaining),
            )
            time.sleep(min(poll_interval, remaining))

        self.logger.warning(
            "[SMS-OTP] Timed out after %ds — no matching SMS OTP received. "
            "Fail-Safe Sequence: Verify phone is connected to 'Link to Windows' with notifications enabled.",
            wait_seconds,
        )
        return None

