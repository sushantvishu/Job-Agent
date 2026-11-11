"""
Unit tests for JobMatcher scoring engine.
Ensures scoring rules, fresher bonuses, experience penalties, and skill matching behave correctly.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.matcher import JobMatcher
from app.utils import JobPosting, MatchResult, ProfileData


def _mock_profile() -> ProfileData:
    return ProfileData(
        name="Test Candidate",
        email="candidate@example.com",
        phone="+91 9999999999",
        headline="Cybersecurity Analyst | VAPT | SOC | Python",
        location="Bengaluru, India",
        preferred_locations=["Bengaluru", "Hyderabad", "Pune", "Remote"],
        notice_period="Immediate",
        expected_salary="As per company standards",
        summary="Cybersecurity analyst with hands-on practice in web application testing, vulnerability assessment, API security, and SOC workflows.",
        experience_years=1.0,
        skills=["VAPT", "OWASP Top 10", "Burp Suite", "API Security", "Nmap", "Python", "Wireshark", "SIEM", "SOC"],
        target_roles=["Cybersecurity Analyst", "VAPT Analyst", "SOC Analyst", "Security Analyst"],
        links={"linkedin": "https://linkedin.com/in/example", "github": "https://github.com/example"},
        custom_answers={"relocation": "Yes", "notice period": "Immediate"},
    )


def test_fresher_vapt_role_scores_high():
    matcher = JobMatcher(_mock_profile())
    job = JobPosting(
        url="https://example.com/job/vapt-fresher",
        source="naukri",
        company="SecureCorp",
        title="Junior VAPT Analyst",
        description="Looking for entry level penetration tester or fresher with knowledge of OWASP Top 10, Burp Suite, and API security. 0-1 years experience.",
        location="Bengaluru",
        experience="0-1 years",
        skills=["VAPT", "OWASP", "Burp Suite", "Python"],
    )
    result = matcher.score(job)
    assert result.score >= 60, f"Expected score >= 60 for fresher VAPT role, got {result.score}"
    assert result.decision in ("strong apply", "apply", "apply after review", "shortlist"), f"Expected shortlist decision, got {result.decision}"
    reasons_text = " ".join(result.reasons).lower()
    assert "owasp" in reasons_text or "vapt" in reasons_text or "target" in reasons_text


def test_senior_role_penalized():
    matcher = JobMatcher(_mock_profile())
    job = JobPosting(
        url="https://example.com/job/senior-lead",
        source="linkedin",
        company="GlobalTech",
        title="Lead Security Architect",
        description="Minimum 8+ years of mandatory enterprise penetration testing experience leading large teams.",
        location="Bengaluru",
        experience="8-12 years",
        skills=["VAPT", "OWASP", "Management"],
    )
    result = matcher.score(job)
    assert result.score < 50, f"Expected low score for 8+ year role, got {result.score}"
    assert result.decision == "skip", f"Expected skip for senior role, got {result.decision}"


def test_non_technical_role_skipped():
    matcher = JobMatcher(_mock_profile())
    job = JobPosting(
        url="https://example.com/job/sales-rep",
        source="naukri",
        company="RetailHub",
        title="Inside Sales Telecaller",
        description="BPO call center voice process for retail credit card sales. Telecalling experience required.",
        location="Bengaluru",
        experience="0-2 years",
    )
    result = matcher.score(job)
    assert result.score < 50, f"Expected skip for telecaller role, got {result.score}"
    assert result.decision == "skip"


def test_python_backend_adjacent_role():
    matcher = JobMatcher(_mock_profile())
    job = JobPosting(
        url="https://example.com/job/python-dev",
        source="linkedin",
        company="FintechApp",
        title="Junior Python Backend Engineer",
        description="We are hiring a Python developer with FastAPI and REST API security knowledge. Freshers welcome (0-1 year exp).",
        location="Remote, India",
        experience="0-1 years",
        skills=["Python", "FastAPI", "API Security"],
    )
    result = matcher.score(job)
    assert result.score >= 50, f"Expected acceptable score for adjacent Python role, got {result.score}"


if __name__ == "__main__":
    print("=" * 60)
    print("  RUNNING JOB MATCHER UNIT TESTS")
    print("=" * 60)
    test_fresher_vapt_role_scores_high()
    print("✅ test_fresher_vapt_role_scores_high PASSED")
    test_senior_role_penalized()
    print("✅ test_senior_role_penalized PASSED")
    test_non_technical_role_skipped()
    print("✅ test_non_technical_role_skipped PASSED")
    test_python_backend_adjacent_role()
    print("✅ test_python_backend_adjacent_role PASSED")
    print("=" * 60)
    print("  🎉 ALL 4 JOB MATCHER TESTS PASSED FLAWLESSLY!")
    print("=" * 60)
