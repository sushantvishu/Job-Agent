"""
app/email_sender.py — Standalone SMTP email sender for job applications.

Sends HTML + plain-text email with PDF resume attachment via Gmail SMTP.
All sends are CC'd to the candidate's own inbox for a paper trail.
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any


logger = logging.getLogger("email_sender")


class DailyQuotaManager:
    """Manages cold outreach email quotas to protect SMTP sender reputation and avoid account flags."""

    def __init__(self, max_per_day: int = 30, state_file: Path | None = None) -> None:
        self.max_per_day = max_per_day
        self.state_file = state_file or Path("logs/email_quota.json")

    def get_today_count(self) -> int:
        if not self.state_file.exists():
            return 0
        try:
            import json
            from datetime import date
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            if data.get("date") == str(date.today()):
                return int(data.get("count", 0))
        except Exception:
            pass
        return 0

    def can_send(self) -> bool:
        return self.get_today_count() < self.max_per_day

    def record_send(self) -> int:
        import json
        from datetime import date
        today_str = str(date.today())
        count = self.get_today_count() + 1
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps({"date": today_str, "count": count}), encoding="utf-8")
        except Exception as exc:
            logger.warning("Could not persist email quota state: %s", exc)
        return count


class EmailSender:
    """
    Sends job application emails via Gmail SMTP (TLS).

    Parameters
    ----------
    sender_email  : Gmail address (e.g. your_email@gmail.com)
    app_password  : Gmail App Password (16-char, spaces stripped)
    smtp_host     : override SMTP host (default: smtp.gmail.com)
    smtp_port     : override SMTP port (default: 587)
    daily_limit   : maximum emails allowed per calendar day (default: 30)
    """

    def __init__(
        self,
        sender_email: str,
        app_password: str,
        sender_name: str = "",
        smtp_host: str = "smtp.gmail.com",
        smtp_port: int = 587,
        daily_limit: int = 30,
        quota_state_file: Path | None = None,
    ) -> None:
        self.sender_email = sender_email
        self.app_password = app_password.replace(" ", "")
        self.sender_name = sender_name
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.quota = DailyQuotaManager(max_per_day=daily_limit, state_file=quota_state_file)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_application_email(
        self,
        to_email: str,
        subject: str,
        body_html: str,
        resume_path: Path,
        cc_email: str | None = None,
        bcc_email: str | None = None,
        plain_body: str | None = None,
        extra_attachments: list[Path] | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Compose and send a job application email with the resume attached.

        Returns (success: bool, message: str).
        When dry_run=True, the email is composed but NOT sent — prints to log only.
        """
        try:
            if not dry_run and not self.quota.can_send():
                msg_str = f"Daily email quota reached ({self.quota.get_today_count()}/{self.quota.max_per_day}). Pausing to protect sender reputation."
                logger.warning(msg_str)
                return False, msg_str

            resume_path = Path(resume_path)
            if not resume_path.exists():
                msg_str = f"Cannot send email: resume file not found at {resume_path}"
                logger.error(msg_str)
                return False, msg_str

            bcc_target = bcc_email if bcc_email is not None else self.sender_email

            msg = self._build_message(
                to_email=to_email,
                subject=subject,
                body_html=body_html,
                plain_body=plain_body,
                resume_path=resume_path,
                cc_email=cc_email,
                extra_attachments=extra_attachments or [],
            )

            if dry_run:
                logger.info(
                    "[DRY RUN] Would send email:\n  To: %s\n  Subject: %s\n  CC: %s\n  BCC: %s\n  Resume: %s",
                    to_email, subject, cc_email, bcc_target, resume_path.name,
                )
                return True, "DRY RUN — email not actually sent"

            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(self.sender_email, self.app_password)
                recipients = [to_email]
                if cc_email and cc_email != to_email:
                    recipients.append(cc_email)
                if bcc_target and bcc_target not in recipients:
                    recipients.append(bcc_target)
                server.sendmail(self.sender_email, recipients, msg.as_bytes())

            self.quota.record_send()
            logger.info(
                "Email sent successfully: To=%s | BCC=%s | Subject=%s | Resume=%s",
                to_email, bcc_target, subject, resume_path.name,
            )
            return True, "Email sent successfully"

        except smtplib.SMTPAuthenticationError as exc:
            msg_str = f"SMTP authentication failed — check Gmail App Password: {exc}"
            logger.error(msg_str)
            return False, msg_str
        except smtplib.SMTPRecipientsRefused as exc:
            msg_str = f"Recipient refused by SMTP: {exc}"
            logger.error(msg_str)
            return False, msg_str
        except Exception as exc:  # noqa: BLE001
            msg_str = f"Email send failed: {exc}"
            logger.error(msg_str)
            return False, msg_str

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_message(
        self,
        to_email: str,
        subject: str,
        body_html: str,
        plain_body: str | None,
        resume_path: Path,
        cc_email: str | None,
        extra_attachments: list[Path],
    ) -> MIMEMultipart:
        msg = MIMEMultipart("mixed")
        from_name = self.sender_name.strip() if self.sender_name else ""
        msg["From"] = f"{from_name} <{self.sender_email}>" if from_name else self.sender_email
        msg["To"] = to_email
        if cc_email:
            msg["CC"] = cc_email
        msg["Subject"] = subject
        msg["Reply-To"] = self.sender_email

        # Body (alternative: plain + html)
        body_part = MIMEMultipart("alternative")
        if plain_body:
            body_part.attach(MIMEText(plain_body, "plain", "utf-8"))
        body_part.attach(MIMEText(body_html, "html", "utf-8"))
        msg.attach(body_part)

        # Resume attachment
        if resume_path.exists():
            with open(resume_path, "rb") as f:
                pdf_data = f.read()
            pdf_part = MIMEApplication(pdf_data, _subtype="pdf")
            pdf_part.add_header(
                "Content-Disposition",
                "attachment",
                filename=resume_path.name,
            )
            msg.attach(pdf_part)
        else:
            logger.warning("Resume file not found at %s — sending without attachment.", resume_path)

        # Extra attachments (cover letter PDF, etc.)
        for attachment_path in extra_attachments:
            if attachment_path.exists():
                with open(attachment_path, "rb") as f:
                    data = f.read()
                part = MIMEApplication(data, _subtype="pdf")
                part.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=attachment_path.name,
                )
                msg.attach(part)

        return msg

    # ------------------------------------------------------------------
    # Test connectivity helper
    # ------------------------------------------------------------------

    def test_connection(self) -> tuple[bool, str]:
        """Verify SMTP credentials without sending anything."""
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.login(self.sender_email, self.app_password)
            return True, "SMTP connection and authentication successful"
        except smtplib.SMTPAuthenticationError as exc:
            return False, f"SMTP auth failed: {exc}"
        except Exception as exc:  # noqa: BLE001
            return False, f"SMTP connection failed: {exc}"

