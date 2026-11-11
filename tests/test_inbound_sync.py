from pathlib import Path
import pytest
from app.inbound_sync import InboundSyncManager, classify_inbound_message
from app.tracker import JobTracker


def test_classify_interview_invite():
    subject = "Interview Invitation: Senior VAPT Specialist at CloudSec"
    sender = "hr@cloudsec.io"
    body = "Hi Candidate, We are pleased to invite you for an interview. Please select a time slot here: https://calendly.com/cloudsec/vapt-interview"
    res = classify_inbound_message(subject, sender, body)
    assert res["intent"] == "INTERVIEW_INVITE"
    assert res["company"] == "CloudSec"
    assert res["meeting_link"] == "https://calendly.com/cloudsec/vapt-interview"


def test_classify_coding_assessment():
    subject = "Technical Assessment for Python Engineer - TechCorp"
    sender = "talent@techcorp.com"
    body = "Please complete your online assessment within 48 hours: https://www.hackerrank.com/tests/techcorp-python"
    res = classify_inbound_message(subject, sender, body)
    assert res["intent"] == "TECHNICAL_ASSESSMENT"
    assert "hackerrank.com" in res["assessment_link"]


def test_classify_rejection():
    subject = "Update on your application with SecurityCorp"
    sender = "noreply@securitycorp.com"
    body = "Thank you for your interest. Unfortunately, after careful consideration, we will not be moving forward with your candidacy."
    res = classify_inbound_message(subject, sender, body)
    assert res["intent"] == "REJECTION"


def test_inbound_manager_process_message(tmp_path: Path):
    db_file = tmp_path / "test_jobs.db"
    tracker = JobTracker(db_file)
    tracker.init_db()

    mgr = InboundSyncManager(tracker=tracker)
    mgr.alerts_file = tmp_path / "interview_alerts.md"

    record = mgr.process_message_payload(
        subject="Interview with Palo Alto Networks",
        sender="recruiter@paloaltonetworks.com",
        body="Join our Google Meet call: https://meet.google.com/abc-defg-hij",
    )
    assert record["intent"] == "INTERVIEW_INVITE"
    assert record["company"] == "Palo Alto Networks"
    assert record["meeting_link"] == "https://meet.google.com/abc-defg-hij"

    interviews = tracker.list_interviews()
    assert len(interviews) == 1
    assert interviews[0]["company"] == "Palo Alto Networks"
    assert mgr.alerts_file.exists()
    assert "Palo Alto Networks" in mgr.alerts_file.read_text(encoding="utf-8")
