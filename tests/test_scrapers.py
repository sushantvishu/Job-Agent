from app.scrapers import NaukriAdapter, LinkedInJobsAdapter, CompanyATSAdapter, JobCandidate


def test_scrapers_can_handle():
    naukri = NaukriAdapter()
    assert naukri.can_handle("https://www.naukri.com/vapt-jobs-in-india")
    assert not naukri.can_handle("https://www.linkedin.com/jobs/search")

    linkedin = LinkedInJobsAdapter()
    assert linkedin.can_handle("https://www.linkedin.com/jobs/view/12345")
    assert not linkedin.can_handle("https://www.naukri.com/job-listings")

    ats = CompanyATSAdapter()
    assert ats.can_handle("https://boards.greenhouse.io/metmox/jobs/123")
    assert ats.can_handle("https://jobs.lever.co/company/abc")
    assert not ats.can_handle("https://www.naukri.com/job")


def test_job_candidate_dataclass():
    cand = JobCandidate(
        url="https://example.com/job/1",
        source="naukri",
        company="SecureCorp",
        title="VAPT Analyst",
        location="Bengaluru",
    )
    assert cand.company == "SecureCorp"
    assert cand.source == "naukri"
