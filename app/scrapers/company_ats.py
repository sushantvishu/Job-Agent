from __future__ import annotations

import logging
from typing import Any
from playwright.sync_api import Page

from app.scrapers.base import BaseJobSource, JobCandidate
from app.utils import JobPosting, compact_whitespace


class CompanyATSAdapter(BaseJobSource):
    """Adapter for extracting job details from external company sites and ATS platforms (Greenhouse, Lever, Workday)."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger("scrapers.company_ats")

    @property
    def source_name(self) -> str:
        return "company"

    def can_handle(self, url: str) -> bool:
        lowered = (url or "").lower()
        return not ("naukri.com" in lowered or "linkedin.com" in lowered)

    def extract_listing_candidates(self, page: Page) -> list[JobCandidate]:
        candidates: list[JobCandidate] = []
        try:
            links = page.locator("a[href*='/job/'], a[href*='/jobs/'], a[href*='/careers/'], a[href*='greenhouse.io'], a[href*='lever.co']").all()
            for link in links:
                href = link.get_attribute("href") or ""
                if not href or href.startswith("#"):
                    continue
                title = compact_whitespace(link.inner_text())
                if len(title) > 3:
                    candidates.append(
                        JobCandidate(
                            url=href,
                            source="company",
                            title=title,
                            location="India",
                        )
                    )
        except Exception as exc:
            self.logger.debug("Company ATS listing extraction: %s", exc)
        return candidates

    def extract_job_detail(self, page: Page, candidate_url: str = "") -> JobPosting:
        url = candidate_url or page.url
        title = ""
        company = ""
        location = "India"
        description = ""

        try:
            # Common ATS title locators
            title_loc = page.locator("h1.app-title, .job-title, h1").first
            if title_loc.count():
                title = compact_whitespace(title_loc.inner_text())

            comp_loc = page.locator(".company-name, [data-qa='company-name']").first
            if comp_loc.count():
                company = compact_whitespace(comp_loc.inner_text())

            loc_loc = page.locator(".location, [data-qa='job-location']").first
            if loc_loc.count():
                location = compact_whitespace(loc_loc.inner_text())

            desc_loc = page.locator("#content, #job-description, .job-description, article").first
            if desc_loc.count():
                description = compact_whitespace(desc_loc.inner_text())
            elif page.locator("body").count():
                description = compact_whitespace(page.locator("body").inner_text()[:4000])
        except Exception as exc:
            self.logger.debug("Company ATS detail extraction: %s", exc)

        return JobPosting(
            url=url,
            source="company",
            title=title,
            company=company,
            location=location,
            description=description,
        )

    def expand_details(self, page: Page) -> None:
        pass
