from pathlib import Path
from app.email_sender import DailyQuotaManager, EmailSender


def test_quota_manager_limit_enforced(tmp_path: Path):
    quota_file = tmp_path / "test_quota.json"
    qm = DailyQuotaManager(max_per_day=2, state_file=quota_file)

    assert qm.get_today_count() == 0
    assert qm.can_send()

    assert qm.record_send() == 1
    assert qm.can_send()

    assert qm.record_send() == 2
    assert not qm.can_send()


def test_email_sender_blocks_when_quota_exhausted(tmp_path: Path):
    quota_file = tmp_path / "sender_quota.json"
    fake_resume = tmp_path / "Resume.pdf"
    fake_resume.write_bytes(b"%PDF-1.4 dummy")

    sender = EmailSender(
        sender_email="test@example.com",
        app_password="dummy",
        daily_limit=1,
        quota_state_file=quota_file,
    )
    # Manually exhaust quota
    sender.quota.record_send()

    success, msg = sender.send_application_email(
        to_email="recruiter@example.com",
        subject="Test Role",
        body_html="<p>Test</p>",
        resume_path=fake_resume,
        dry_run=False,
    )
    assert not success
    assert "daily email quota reached" in msg.lower()
