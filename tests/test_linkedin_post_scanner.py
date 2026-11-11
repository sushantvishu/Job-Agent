"""
Unit and regression tests for the LinkedIn Post Email Applier.
Verifies:
1. Strict 3-week post age filtering (<= 3 weeks accepted, > 3 weeks rejected)
2. Experience filtering (freshers, 0-6m, 6m-1yr, 1-2yr accepted; 3+ yrs rejected)
3. Email extraction and noise domain filtering
4. Subject line extraction according to post instructions
5. Email composition (HTML + Plain text + Signature)
6. PostEmailTracker SQLite persistence & migrations
"""
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.linkedin_post_scanner import (
    LinkedInPostScanner,
    LinkedInPostLead,
    AGE_REJECT_PATTERNS,
    AGE_ACCEPT_PATTERNS,
    EMAIL_REGEX,
    SUBJECT_PATTERNS,
    FRESHER_KEYWORDS,
    SENIOR_KEYWORDS,
)
from app.cover_email_composer import CoverEmailComposer
from app.post_email_tracker import PostEmailTracker


def test_post_age_filter():
    """Verify strictly: posts older than 3 weeks are rejected, <= 3 weeks accepted."""
    # Test cases that MUST BE REJECTED (> 3 weeks / 21 days)
    old_cases = [
        "4w • Edited",
        "5w •",
        "4 weeks ago",
        "5 weeks ago",
        "1 month ago",
        "2 months ago",
        "1mo • Edited",
        "3mo •",
        "1 year ago",
        "1yr •",
        "1y •",
        "25 days ago",
        "30 days ago",
    ]
    for case in old_cases:
        valid, desc = LinkedInPostScanner._is_within_3_weeks(text="", time_text=case)
        assert not valid, f"Failed: {case!r} should be rejected as older than 3 weeks, but got: {desc}"

    # Test cases that MUST BE ACCEPTED (<= 3 weeks / 21 days)
    fresh_cases = [
        "1w • Edited",
        "2w •",
        "3w •",
        "1 week ago",
        "2 weeks ago",
        "3 weeks ago",
        "1d •",
        "5d •",
        "14d •",
        "21d •",
        "1 day ago",
        "5 days ago",
        "21 days ago",
        "12h •",
        "30m •",
        "2 hours ago",
        "just now",
        "today",
        "yesterday",
    ]
    for case in fresh_cases:
        valid, desc = LinkedInPostScanner._is_within_3_weeks(text="", time_text=case)
        assert valid, f"Failed: {case!r} should be accepted within 3 weeks, but got: {desc}"

    print("✅ test_post_age_filter PASSED (all 3-week boundary checks verified)")


def test_experience_filter():
    """Verify experience filtering for 0-6m, 6m-1yr, 1-2yr vs 3+ years."""
    # Fresher cases (0 to 2 years)
    fresher_cases = [
        "Hiring VAPT fresher for our Bangalore office",
        "Looking for 0-1 year experience cybersecurity analyst",
        "Cyber security internship for 6 months",
        "Junior SOC Analyst (0-2 years exp)",
        "Entry level penetration tester needed",
        "Trainee in Application Security, send CV",
        "6 months - 1 year experience required",
        "1-2 years experience in Burp Suite and OWASP",
    ]
    for text in fresher_cases:
        assert LinkedInPostScanner._is_fresher_eligible(text.lower()), f"Failed to identify fresher text: {text}"
        assert not LinkedInPostScanner._has_senior_requirement(text.lower()), f"False positive senior flag on: {text}"

    # Senior cases (must be rejected)
    senior_cases = [
        "Looking for Lead Pentester with 5+ years of experience",
        "Senior Security Consultant (minimum 4 years required)",
        "Team lead with 3+ years in SOC operations",
        "Senior Manager VAPT (8+ years experience)",
    ]
    for text in senior_cases:
        assert LinkedInPostScanner._has_senior_requirement(text.lower()), f"Failed to identify senior text: {text}"

    print("✅ test_experience_filter PASSED (0-2 yr vs 3+ yr screening verified)")


def test_email_and_subject_extraction():
    """Verify recruiter email address and post instruction subject line extraction."""
    post_text = """
    We are urgently hiring for Junior VAPT Analyst!
    Experience: 0-1 year / Fresher
    Location: Bengaluru / Remote
    Skills: OWASP Top 10, Burp Suite, Network Security
    Interested candidates please send your resume to careers@secops-india.com
    Mention in subject: Application for Junior VAPT Analyst - Bengaluru
    Immediate joiners preferred.
    """
    emails = LinkedInPostScanner._extract_emails(post_text)
    assert "careers@secops-india.com" in emails, f"Email extraction failed: {emails}"

    subject = LinkedInPostScanner._extract_subject(post_text)
    assert "Application for Junior VAPT Analyst - Bengaluru" in subject, f"Subject extraction failed: {subject}"

    role = LinkedInPostScanner._extract_role(post_text)
    assert role == "VAPT Analyst", f"Role extraction failed: {role}"

    # Test obfuscated anti-bot email extraction
    obfuscated_texts = [
        "Send your CV to hr [at] cybersec.com for VAPT fresher role",
        "Reach out at jobs(at)defensetech(dot)in with resume",
        "Email resume: recruiter at securitycorp.com with subject Application",
    ]
    assert "hr@cybersec.com" in LinkedInPostScanner._extract_emails(obfuscated_texts[0])
    assert "jobs@defensetech.in" in LinkedInPostScanner._extract_emails(obfuscated_texts[1])
    assert "recruiter@securitycorp.com" in LinkedInPostScanner._extract_emails(obfuscated_texts[2])

    # Test subject line placeholder substitution
    sub_placeholder = 'Please use Subject: "Application for VAPT Trainee - [Your Name]"'
    extracted_sub = LinkedInPostScanner._extract_subject(sub_placeholder)
    assert "Application for VAPT Trainee" in extracted_sub, f"Placeholder failed: {extracted_sub}"

    # Test company extraction from recruiter headline
    company_from_headline = LinkedInPostScanner._extract_company("Hiring VAPT freshers", headline="Senior HR Specialist at CyberDefense Corp")
    assert company_from_headline == "CyberDefense Corp", f"Headline company extraction failed: {company_from_headline}"

    print("✅ test_email_and_subject_extraction PASSED (recruiter email & instructions parsed)")


def test_cover_email_composition():
    """Verify cover email composition with tailored candidate background."""
    composer = CoverEmailComposer(ollama_client=None)
    html, plain = composer.compose(
        role="VAPT Analyst",
        company="SecureTech Solutions",
        poster_name="Priya Nair",
        skills_mentioned=["vapt", "burp suite", "owasp", "python"],
        job_context="Hiring VAPT fresher. Send resume to hr@securetech.com",
    )
    assert "Priya Nair" in html and "Priya Nair" in plain
    candidate_name = composer.profile.name if composer.profile and composer.profile.name else "Candidate"
    assert candidate_name in html and candidate_name in plain
    assert "VAPT Analyst" in html and "SecureTech Solutions" in html
    assert "1 year" in html or "1.0" in html
    if composer.profile and composer.profile.email:
        assert composer.profile.email in html
    if composer.profile and composer.profile.phone:
        assert composer.profile.phone in html
    assert len(html) > 300
    print("✅ test_cover_email_composition PASSED (HTML + Plain text + Signature generated)")


def test_post_email_tracker_db():
    """Verify SQLite tracking and deduplication."""
    db_file = Path("d:/job-agent/tests/test_tracker.db")
    if db_file.exists():
        db_file.unlink()

    tracker = PostEmailTracker(db_file)
    tracker.init_table()

    # Record dry run attempt
    tracker.record_attempt(
        post_url="https://www.linkedin.com/posts/test-post-1",
        poster_name="Recruiter One",
        company="CyberCorp",
        role="SOC Analyst",
        email_to="hr@cybercorp.com",
        email_subject="Application for SOC Analyst",
        email_body="Dear Hiring Team...",
        status="sent",
        reason="Test send",
        post_age="2d",
    )

    # Check already sent
    assert tracker.is_already_sent("https://www.linkedin.com/posts/test-post-1", "hr@cybercorp.com")
    assert not tracker.is_already_sent("https://www.linkedin.com/posts/test-post-2", "hr@cybercorp.com")

    stats = tracker.get_stats()
    assert stats.get("sent") == 1

    if db_file.exists():
        db_file.unlink()

    print("✅ test_post_email_tracker_db PASSED (SQLite tracking & dedup verified)")


if __name__ == "__main__":
    print("=" * 65)
    print("  RUNNING LINKEDIN POST SCANNER & EMAIL APPLIER TEST SUITE")
    print("=" * 65)
    test_post_age_filter()
    test_experience_filter()
    test_email_and_subject_extraction()
    test_cover_email_composition()
    test_post_email_tracker_db()
    print("=" * 65)
    print("  🎉 ALL 5 TEST SUITES PASSED FLAWLESSLY!")
    print("=" * 65)
