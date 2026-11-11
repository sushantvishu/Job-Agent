from app.matcher import JobMatcher
from app.utils import JobPosting, ProfileData


def test_disqualifying_academic_and_teaching_roles():
    profile = ProfileData(
        name="Candidate Name",
        email="candidate@example.com",
        phone="+919876543210",
        location="Bengaluru, India",
        skills=["Python", "VAPT", "SOC"],
        target_roles=["Python Developer", "VAPT Analyst"],
    )
    matcher = JobMatcher(profile)

    # Academic/Teaching Requisitions must be disqualified immediately
    academic_job = JobPosting(
        url="https://in.linkedin.com/jobs/view/123",
        source="linkedin",
        company="Apeejay Education",
        title="Assistant Professor - Cyber Security and Block Chain",
        location="Bengaluru, India",
    )
    res = matcher.score(academic_job)
    assert res.score == 0
    assert res.decision == "skip"
    assert any("negative role keyword" in r.lower() for r in res.reasons)

    # Non-technical sales/BPO role must be disqualified
    bpo_job = JobPosting(
        url="https://in.linkedin.com/jobs/view/456",
        source="linkedin",
        company="Global Teleservices",
        title="Telecaller / Inside Sales Executive",
        location="Bengaluru, India",
    )
    res_bpo = matcher.score(bpo_job)
    assert res_bpo.score == 0
    assert res_bpo.decision == "skip"

    # Genuine technical role must NOT be disqualified
    tech_job = JobPosting(
        url="https://in.linkedin.com/jobs/view/789",
        source="linkedin",
        company="Cyber Defence Labs",
        title="Junior VAPT Analyst",
        location="Bengaluru, India",
        description="Hands-on web application penetration testing using Burp Suite and OWASP Top 10.",
    )
    res_tech = matcher.score(tech_job)
    assert res_tech.score > 0
    assert res_tech.decision != "skip"
