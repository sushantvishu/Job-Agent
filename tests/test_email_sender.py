import sys
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.email_sender import EmailSender


def test_missing_resume_blocks_sending(tmp_path: Path):
    sender = EmailSender(
        sender_email="candidate@example.com",
        app_password="dummy_password",
        sender_name="Candidate Name",
    )
    non_existent_resume = tmp_path / "NonExistentResume.pdf"
    
    success, msg = sender.send_application_email(
        to_email="recruiter@example.com",
        subject="Application for VAPT Analyst",
        body_html="<p>Please find attached resume.</p>",
        resume_path=non_existent_resume,
    )
    assert not success
    assert "resume file not found" in msg.lower()


def test_dry_run_with_valid_resume(tmp_path: Path):
    sender = EmailSender(
        sender_email="candidate@example.com",
        app_password="dummy_password",
        sender_name="Candidate Name",
    )
    fake_resume = tmp_path / "Candidate_CV.pdf"
    fake_resume.write_bytes(b"%PDF-1.4 dummy content")
    
    success, msg = sender.send_application_email(
        to_email="recruiter@example.com",
        subject="Application for VAPT Analyst",
        body_html="<p>Please find attached resume.</p>",
        plain_body="Please find attached resume.",
        resume_path=fake_resume,
        dry_run=True,
    )
    assert success
    assert "DRY RUN" in msg


def test_message_builder(tmp_path: Path):
    sender = EmailSender(
        sender_email="candidate@example.com",
        app_password="dummy_password",
        sender_name="Candidate Name",
    )
    fake_resume = tmp_path / "Candidate_CV.pdf"
    fake_resume.write_bytes(b"%PDF-1.4 dummy content")

    msg = sender._build_message(
        to_email="recruiter@example.com",
        subject="Application for VAPT Analyst",
        body_html="<p>HTML Body</p>",
        plain_body="Plain Body",
        resume_path=fake_resume,
        cc_email=None,
        extra_attachments=[],
    )
    assert msg["To"] == "recruiter@example.com"
    assert "Candidate Name" in msg["From"]
    assert msg["Subject"] == "Application for VAPT Analyst"
