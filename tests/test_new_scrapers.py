import logging
from app.job_collector import JobCollector
from app.scrapers.instahyre import InstahyreAdapter
from app.scrapers.foundit import FounditAdapter
from app.scrapers.wellfound import WellfoundAdapter


def test_instahyre_adapter():
    adapter = InstahyreAdapter()
    assert adapter.source_name == "instahyre"
    assert adapter.can_handle("https://www.instahyre.com/job-12345-python-dev")
    assert not adapter.can_handle("https://www.linkedin.com/jobs/view/123")


def test_foundit_adapter():
    adapter = FounditAdapter()
    assert adapter.source_name == "foundit"
    assert adapter.can_handle("https://www.foundit.in/job/54321")
    assert adapter.can_handle("https://www.monsterindia.com/job/54321")
    assert not adapter.can_handle("https://naukri.com/job-listings")


def test_wellfound_adapter():
    adapter = WellfoundAdapter()
    assert adapter.source_name == "wellfound"
    assert adapter.can_handle("https://wellfound.com/jobs/123")
    assert adapter.can_handle("https://angel.co/company/abc/jobs/123")
    assert not adapter.can_handle("https://naukri.com")


def test_job_collector_resolves_all_adapters():
    collector = JobCollector(logging.getLogger())
    assert isinstance(collector.get_adapter("https://www.instahyre.com/job-1"), InstahyreAdapter)
    assert isinstance(collector.get_adapter("https://www.foundit.in/job/2"), FounditAdapter)
    assert isinstance(collector.get_adapter("https://wellfound.com/jobs/3"), WellfoundAdapter)
