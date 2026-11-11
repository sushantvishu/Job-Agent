from __future__ import annotations

import email
import imaplib
import logging
import re
from datetime import datetime
from email.header import decode_header
from pathlib import Path
from typing import Any

from app.config import AppConfig, load_config
from app.tracker import JobTracker
from app.utils import normalize_key

logger = logging.getLogger("inbound_sync")

# Patterns for link extraction
MEETING_PATTERNS = [
    r"https?://(?:[a-zA-Z0-9-]+\.)?calendly\.com/[^\s\"'>]+",
    r"https?://meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}",
    r"https?://(?:[a-zA-Z0-9-]+\.)?zoom\.us/(?:j|my)/[^\s\"'>]+",
    r"https?://teams\.microsoft\.com/l/meetup-join/[^\s\"'>]+",
]

ASSESSMENT_PATTERNS = [
    r"https?://(?:[a-zA-Z0-9-]+\.)?hackerrank\.com/[^\s\"'>]+",
    r"https?://(?:[a-zA-Z0-9-]+\.)?codility\.com/[^\s\"'>]+",
    r"https?://(?:[a-zA-Z0-9-]+\.)?testgorilla\.com/[^\s\"'>]+",
    r"https?://(?:[a-zA-Z0-9-]+\.)?hackerearth\.com/[^\s\"'>]+",
    r"https?://(?:[a-zA-Z0-9-]+\.)?mettl\.com/[^\s\"'>]+",
]

# Classification keywords
INTENT_KEYWORDS: dict[str, list[str]] = {
    "OFFER": [
        "offer letter", "job offer", "pleased to offer", "congratulations on your offer",
        "formal offer", "employment offer"
    ],
    "INTERVIEW_INVITE": [
        "interview", "discussion", "technical round", "telephonic round", "f2f round",
        "video call", "calendly", "google meet", "teams meeting", "zoom meeting",
        "schedule a call", "invitation for interview", "shortlisted for", "next round",
        "availability for a quick call", "convenient time for an interview"
    ],
    "TECHNICAL_ASSESSMENT": [
        "assessment", "online test", "coding test", "coding challenge", "hackerrank",
        "codility", "take-home test", "technical evaluation", "aptitude test", "screening test"
    ],
    "REJECTION": [
        "unfortunately", "regret to inform", "not moving forward", "pursuing other candidates",
        "decided to proceed with another", "cannot offer you", "wishing you success in your job search",
        "better suited"
    ],
    "MORE_INFO_REQUESTED": [
        "updated resume", "share your portfolio", "notice period and current ctc",
        "please share the following details", "confirm your availability", "salary expectation"
    ],
}


def clean_header_text(header_val: str | None) -> str:
    """Safely decode RFC 2047 MIME encoded headers."""
    if not header_val:
        return ""
    decoded_parts: list[str] = []
    for part, enc in decode_header(header_val):
        if isinstance(part, bytes):
            decoded_parts.append(part.decode(enc or "utf-8", errors="ignore"))
        else:
            decoded_parts.append(str(part))
    return " ".join(decoded_parts).strip()


def extract_links(text: str, patterns: list[str]) -> list[str]:
    """Find URLs matching given regex patterns."""
    found: list[str] = []
    for pattern in patterns:
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        for m in matches:
            cleaned = m.rstrip(".,;)>'\"")
            if cleaned not in found:
                found.append(cleaned)
    return found


def classify_inbound_message(subject: str, sender: str, body: str) -> dict[str, Any]:
    """Classify incoming recruiter email intent, extract meeting/assessment links and deadlines."""
    combined = f"{subject}\n{body}".lower()

    detected_intent = "ACKNOWLEDGEMENT"
    # Priority order: OFFER > INTERVIEW_INVITE > TECHNICAL_ASSESSMENT > REJECTION > MORE_INFO_REQUESTED
    for intent in ("OFFER", "INTERVIEW_INVITE", "TECHNICAL_ASSESSMENT", "REJECTION", "MORE_INFO_REQUESTED"):
        for kw in INTENT_KEYWORDS[intent]:
            if kw in combined:
                detected_intent = intent
                break
        if detected_intent != "ACKNOWLEDGEMENT":
            break

    meeting_links = extract_links(body, MEETING_PATTERNS)
    assessment_links = extract_links(body, ASSESSMENT_PATTERNS)

    # Attempt to extract company name from subject or sender
    company = ""
    # Try regex on subject: e.g. "Interview at Microsoft", "Google - Next Steps"
    match = re.search(r"(?:at|with|from|-|@)\s+([A-Za-z0-9\s&]{2,30})", subject)
    if match:
        company = match.group(1).strip()
    elif "@" in sender:
        domain = sender.split("@")[-1]
        domain_name = domain.split(".")[0]
        if domain_name not in ("gmail", "yahoo", "outlook", "hotmail", "zoho"):
            company = domain_name.capitalize()

    return {
        "intent": detected_intent,
        "company": company,
        "meeting_link": meeting_links[0] if meeting_links else None,
        "assessment_link": assessment_links[0] if assessment_links else None,
        "raw_snippet": (body[:400] + "...") if len(body) > 400 else body,
    }


class InboundSyncManager:
    """Manages autonomous IMAP sync and email payload ingestion for recruiter triage."""

    def __init__(self, config: AppConfig | None = None, tracker: JobTracker | None = None) -> None:
        self.config = config or load_config()
        self.tracker = tracker or JobTracker(self.config.db_path)
        self.tracker.init_db()
        self.alerts_file = self.config.exports_dir / "interview_alerts.md"

    def process_message_payload(self, subject: str, sender: str, body: str) -> dict[str, Any]:
        """Ingest a single email payload, classify it, associate it with jobs.db, and record alert."""
        classification = classify_inbound_message(subject, sender, body)
        company = classification["company"]
        matched_job = None
        if company:
            matched_job = self.tracker.find_job_by_company(company)

        job_id = matched_job["id"] if matched_job else None
        role = matched_job["title"] if matched_job else None

        interview_id = self.tracker.record_interview(
            company=company or "Direct Outreach",
            role=role,
            job_id=job_id,
            intent=classification["intent"],
            recruiter_email=sender,
            meeting_link=classification["meeting_link"],
            assessment_link=classification["assessment_link"],
            raw_snippet=classification["raw_snippet"],
        )

        record = {
            "interview_id": interview_id,
            "company": company or "Direct Outreach",
            "role": role or "N/A",
            "intent": classification["intent"],
            "meeting_link": classification["meeting_link"],
            "assessment_link": classification["assessment_link"],
            "sender": sender,
            "subject": subject,
            "matched_job_id": job_id,
        }

        self._append_to_alerts(record)
        return record

    def _append_to_alerts(self, record: dict[str, Any]) -> None:
        """Append actionable alert to exports/interview_alerts.md."""
        self.alerts_file.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        action_badge = "🚨 **HIGH PRIORITY ACTION REQUIRED**" if record["intent"] in ("INTERVIEW_INVITE", "OFFER", "TECHNICAL_ASSESSMENT") else "ℹ️ **INFORMATIONAL**"

        alert_entry = (
            f"\n### [{stamp}] {action_badge} - {record['intent']}\n"
            f"- **Company:** {record['company']}\n"
            f"- **Role:** {record['role']}\n"
            f"- **Recruiter / Sender:** {record['sender']}\n"
            f"- **Subject:** {record['subject']}\n"
        )
        if record.get("meeting_link"):
            alert_entry += f"- **📅 Meeting Link:** [{record['meeting_link']}]({record['meeting_link']})\n"
        if record.get("assessment_link"):
            alert_entry += f"- **📝 Assessment Link:** [{record['assessment_link']}]({record['assessment_link']})\n"
        alert_entry += f"- **Database Record:** Interview #{record['interview_id']} (Job #{record['matched_job_id'] or 'Unlinked'})\n---\n"

        if not self.alerts_file.exists():
            header = "# Recruiter Inbound & Interview Action Alerts\nAutomated real-time interview invitation and screening tracker.\n\n"
            self.alerts_file.write_text(header + alert_entry, encoding="utf-8")
        else:
            with self.alerts_file.open("a", encoding="utf-8") as f:
                f.write(alert_entry)

    def sync_imap_inbox(self, max_messages: int = 15) -> list[dict[str, Any]]:
        """Connect to IMAP server and fetch recent recruiter messages."""
        imap_host = self.config.otp_email_imap_host
        user = self.config.otp_email_address
        password = self.config.otp_email_app_password.get_secret_value()

        if not user or not password:
            logger.warning("InboundSync: OTP_EMAIL_ADDRESS or OTP_EMAIL_APP_PASSWORD not configured. Skipping IMAP sync.")
            return []

        processed: list[dict[str, Any]] = []
        try:
            mail = imaplib.IMAP4_SSL(imap_host, timeout=20.0)
            mail.login(user, password)
            mail.select("INBOX")

            # Search recent unread or all recent
            status, response = mail.search(None, "UNSEEN")
            msg_ids = response[0].split()
            if not msg_ids:
                status, response = mail.search(None, "ALL")
                msg_ids = response[0].split()

            # Take latest N
            target_ids = msg_ids[-max_messages:] if len(msg_ids) > max_messages else msg_ids
            target_ids.reverse()

            for msg_id in target_ids:
                status, data = mail.fetch(msg_id, "(RFC822)")
                if status != "OK" or not data:
                    continue
                raw_email = data[0][1]
                if not isinstance(raw_email, bytes):
                    continue
                msg = email.message_from_bytes(raw_email)

                subject = clean_header_text(msg.get("Subject", ""))
                sender = clean_header_text(msg.get("From", ""))

                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        if content_type == "text/plain":
                            payload = part.get_payload(decode=True)
                            if payload:
                                body += payload.decode("utf-8", errors="ignore")
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body = payload.decode("utf-8", errors="ignore")

                # If email contains career / recruitment signals, process it
                if any(kw in (subject + body).lower() for kwlist in INTENT_KEYWORDS.values() for kw in kwlist):
                    res = self.process_message_payload(subject=subject, sender=sender, body=body)
                    processed.append(res)

            mail.close()
            mail.logout()
        except Exception as exc:
            logger.error("InboundSync error during IMAP fetch: %s", exc)
        return processed
