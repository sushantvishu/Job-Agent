from __future__ import annotations

import email
import imaplib
import os
import re
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.message import Message
from pathlib import Path
from typing import Any

from app.utils import compact_whitespace, load_json, normalize_key, save_json

ACTION_KEYWORDS = {
    "action required",
    "add more details",
    "assessment",
    "complete application",
    "complete your application",
    "continue application",
    "continue your application",
    "document required",
    "email verification",
    "interview",
    "job application",
    "next step",
    "please confirm",
    "recruiter",
    "schedule",
    "shortlisted",
    "test",
    "upload document",
    "verify email",
    "verify your email",
}

NOISE_KEYWORDS = {
    "newsletter",
    "password reset",
    "promotional",
    "unsubscribe",
}

DEFAULT_FOLDERS = {
    "gmail": ["INBOX", "[Gmail]/Spam"],
    "yahoo": ["INBOX", "Bulk Mail", "Spam"],
}


@dataclass
class FollowupHit:
    account: str
    folder: str
    date: str
    sender: str
    subject: str
    matched_company: str
    reason: str
    snippet: str


class EmailFollowupMonitor:
    def __init__(self, accounts_path: Path, exports_dir: Path, logger, ollama_client=None) -> None:
        self.accounts_path = accounts_path
        self.exports_dir = exports_dir
        self.logger = logger
        self.ollama_client = ollama_client

    def write_template(self) -> Path:
        template_path = self.accounts_path.with_suffix(".example.json")
        payload = {
            "accounts": [
                {
                    "name": "gmail_primary",
                    "provider": "gmail",
                    "email": "your-first@gmail.com",
                    "username": "your-first@gmail.com",
                    "password_env": "JOB_AGENT_GMAIL_PRIMARY_APP_PASSWORD",
                },
                {
                    "name": "gmail_secondary",
                    "provider": "gmail",
                    "email": "your-second@gmail.com",
                    "username": "your-second@gmail.com",
                    "password_env": "JOB_AGENT_GMAIL_SECONDARY_APP_PASSWORD",
                },
                {
                    "name": "yahoo",
                    "provider": "yahoo",
                    "email": "your-yahoo@yahoo.com",
                    "username": "your-yahoo@yahoo.com",
                    "password_env": "JOB_AGENT_YAHOO_APP_PASSWORD",
                },
            ]
        }
        from app.utils import save_json
        save_json(template_path, payload)
        return template_path

    def scan(self, tracked_jobs: list[dict[str, Any]], days: int = 30, max_per_folder: int = 50) -> tuple[Path, list[FollowupHit]]:
        accounts = self._load_accounts()
        company_names = self._company_names(tracked_jobs)
        hits: list[FollowupHit] = []
        since = datetime.now() - timedelta(days=max(1, days))

        for account in accounts:
            hits.extend(self._scan_account(account, company_names, since, max_per_folder))

        output = self._write_report(hits, days)
        return output, hits

    def _load_accounts(self) -> list[dict[str, Any]]:
        payload = load_json(self.accounts_path, default={}) or {}
        accounts = payload.get("accounts", []) if isinstance(payload, dict) else []
        return [account for account in accounts if isinstance(account, dict)]

    @staticmethod
    def _company_names(tracked_jobs: list[dict[str, Any]]) -> list[str]:
        companies = []
        for row in tracked_jobs:
            if row.get("status") not in {"applied", "filled_pending_submit", "needs_manual_input"}:
                continue
            company = compact_whitespace(row.get("company") or "")
            if company and normalize_key(company) not in {"unknown", "unknown company"}:
                companies.append(company)
        return sorted(set(companies), key=lambda value: value.lower())

    def _scan_account(
        self,
        account: dict[str, Any],
        company_names: list[str],
        since: datetime,
        max_per_folder: int,
    ) -> list[FollowupHit]:
        provider = (account.get("provider") or "").lower()
        host = account.get("imap_host") or ("imap.mail.yahoo.com" if provider == "yahoo" else "imap.gmail.com")
        username = account.get("username") or account.get("email")
        password_env = account.get("password_env") or ""
        password = os.getenv(password_env)
        account_name = account.get("name") or account.get("email") or username or "unknown"
        folders = account.get("folders") or DEFAULT_FOLDERS.get(provider, ["INBOX", "Spam"])

        if not username or not password:
            self.logger.warning("Skipping email account %s because username or password env is missing", account_name)
            return []

        hits: list[FollowupHit] = []
        mailbox = None
        try:
            ssl_context = ssl.create_default_context()
            mailbox = imaplib.IMAP4_SSL(host, ssl_context=ssl_context)
            mailbox.login(username, password)
            since_query = since.strftime("%d-%b-%Y")
            for folder in folders:
                try:
                    status, _ = mailbox.select(f'"{folder}"', readonly=True)
                    if status != "OK":
                        continue
                    status, data = mailbox.search(None, "SINCE", since_query)
                    if status != "OK" or not data:
                        continue
                    message_ids = data[0].split()[-max_per_folder:]
                    for message_id in reversed(message_ids):
                        hit = self._read_message(mailbox, message_id, account_name, folder, company_names)
                        if hit:
                            hits.append(hit)
                except Exception as exc:  # noqa: BLE001
                    self.logger.debug("Unable to scan %s/%s: %s", account_name, folder, exc)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Unable to connect to email account %s: %s", account_name, exc)
        finally:
            if mailbox:
                try:
                    mailbox.logout()
                except Exception:  # noqa: BLE001
                    pass
        return hits

    def _read_message(
        self,
        mailbox: imaplib.IMAP4_SSL,
        message_id: bytes,
        account_name: str,
        folder: str,
        company_names: list[str],
    ) -> FollowupHit | None:
        status, data = mailbox.fetch(message_id, "(BODY.PEEK[])")
        if status != "OK" or not data or not isinstance(data[0], tuple):
            return None

        msg = email.message_from_bytes(data[0][1])
        subject = self._decode_header(msg.get("Subject", ""))
        sender = self._decode_header(msg.get("From", ""))
        date_value = self._decode_header(msg.get("Date", ""))
        body = self._body_text(msg)
        searchable = normalize_key(f"{subject} {sender} {body}")
        if any(noise in searchable for noise in NOISE_KEYWORDS):
            return None

        action_hits = [keyword for keyword in ACTION_KEYWORDS if normalize_key(keyword) in searchable]
        matched_company = self._match_company(searchable, sender, company_names)
        if not action_hits and not matched_company:
            return None
        if not action_hits and matched_company:
            action_hits = ["message from applied company"]

        return FollowupHit(
            account=account_name,
            folder=folder,
            date=date_value,
            sender=sender,
            subject=subject,
            matched_company=matched_company,
            reason=", ".join(sorted(action_hits)[:5]),
            snippet=compact_whitespace(body)[:500],
        )

    @staticmethod
    def _decode_header(value: str) -> str:
        try:
            return str(make_header(decode_header(value)))
        except Exception:  # noqa: BLE001
            return value

    @staticmethod
    def _body_text(msg: Message) -> str:
        chunks: list[str] = []
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition = (part.get("Content-Disposition") or "").lower()
                if "attachment" in disposition or content_type not in {"text/plain", "text/html"}:
                    continue
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                charset = part.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="ignore")
                if content_type == "text/html":
                    text = re.sub(r"<[^>]+>", " ", text)
                chunks.append(text)
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                chunks.append(payload.decode(charset, errors="ignore"))
        return compact_whitespace(" ".join(chunks))

    @staticmethod
    def _match_company(searchable: str, sender: str, company_names: list[str]) -> str:
        sender_key = normalize_key(sender)
        for company in company_names:
            company_key = normalize_key(company)
            if company_key and (company_key in searchable or company_key in sender_key):
                return company
        return ""

    def _write_report(self, hits: list[FollowupHit], days: int) -> Path:
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        output = self.exports_dir / "application_email_followups_latest.md"
        lines = ["# Application Email Follow-ups", "", f"Window: last {days} days", ""]
        if not hits:
            lines.append("No action-required application follow-ups found.")
        for index, hit in enumerate(hits, start=1):
            lines.extend(
                [
                    f"## {index}. {hit.subject or 'No subject'}",
                    "",
                    f"- Account: {hit.account}",
                    f"- Folder: {hit.folder}",
                    f"- Date: {hit.date or '-'}",
                    f"- Sender: {hit.sender or '-'}",
                    f"- Matched company: {hit.matched_company or '-'}",
                    f"- Reason: {hit.reason or '-'}",
                    f"- Snippet: {hit.snippet or '-'}",
                    "",
                ]
            )
            
            # Automatically draft a response if LLM is available
            if getattr(self, "ollama_client", None) and ("interview" in (hit.reason or "").lower() or "schedule" in (hit.reason or "").lower()):
                prompt = (
                    f"Write a highly professional and concise email reply to the following recruiter message. "
                    f"Express gratitude for the interview opportunity, and propose three available time slots for next week "
                    f"(e.g., Tuesday at 10 AM, Wednesday at 2 PM, Thursday at 11 AM in IST timezone). "
                    f"Keep it under 4 sentences.\n\nRecruiter message:\n{hit.snippet}"
                )
                try:
                    draft = self.ollama_client.generate(prompt=prompt)
                    lines.extend([
                        "### 🤖 Auto-Drafted Reply (AI)",
                        "```text",
                        draft.strip(),
                        "```",
                        ""
                    ])
                except Exception as e:
                    self.logger.warning("Failed to auto-draft email: %s", e)

        output.write_text("\n".join(lines), encoding="utf-8")
        return output
