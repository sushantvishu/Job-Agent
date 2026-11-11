from pathlib import Path
from app.utils import JobPosting
from app.walkin import emit_walkin_brief, extract_walkin_details, is_walkin_requisition


def test_is_walkin_detection():
    assert is_walkin_requisition("Walk-In Interview For SOC Analyst @ Indecomm")
    assert is_walkin_requisition("Walk-in Drive || Software Engineer")
    assert is_walkin_requisition("Direct Walkin - Python Developer")
    assert not is_walkin_requisition("Senior Python Developer (Full Time)")
    assert not is_walkin_requisition("VAPT Analyst - Remote")


def test_walkin_extraction_and_brief(tmp_path: Path):
    job = JobPosting(
        url="https://example.com/walkin-job",
        source="naukri",
        company="Enterprise Tech Corp",
        title="Walk-In Interview for Cyber Security Fresher",
        location="Bengaluru",
        raw_text="""
        Walk-In Interview for Cyber Security Fresher
        Dates: 15th Nov to 18th Nov 2026
        Timings: 10:00 AM - 3:00 PM
        Venue: Tech Park, Tower B, 4th Floor, Electronic City, Bengaluru
        Contact SPOC: Priya Sharma (HR)
        Mandatory: Bring 2 copies of updated resume.
        """,
    )
    details = extract_walkin_details(job)
    assert details["company"] == "Enterprise Tech Corp"
    assert "15th Nov" in details["interview_date"] or "Nov" in details["interview_date"]
    assert "Tech Park" in details["venue"]

    output_brief = tmp_path / "walkin_interviews.md"
    written_path = emit_walkin_brief([details], output_brief)
    assert written_path.exists()
    content = written_path.read_text(encoding="utf-8")
    assert "Enterprise Tech Corp" in content
    assert "Tech Park" in content
