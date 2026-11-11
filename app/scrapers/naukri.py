from __future__ import annotations

import logging
from typing import Any
from playwright.sync_api import Page

from app.scrapers.base import BaseJobSource, JobCandidate
from app.utils import JobPosting, compact_whitespace


class NaukriAdapter(BaseJobSource):
    """Adapter for extracting job listings and details from Naukri.com."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger("scrapers.naukri")

    @property
    def source_name(self) -> str:
        return "naukri"

    def can_handle(self, url: str) -> bool:
        lowered = (url or "").lower()
        return "naukri.com" in lowered

    def extract_listing_candidates(self, page: Page) -> list[JobCandidate]:
        candidates: list[JobCandidate] = []
        try:
            cards = page.locator("article.jobTuple, div.srp-jobtuple-wrapper, div.cust-job-tuple").all()
            for card in cards:
                try:
                    title_loc = card.locator("a.title").first
                    comp_loc = card.locator("a.comp-name, a.subTitle").first
                    loc_loc = card.locator("span.locWdth, span.location").first

                    url = title_loc.get_attribute("href") if title_loc.count() else ""
                    if not url:
                        continue
                    clean_url = url.split("?")[0]
                    title = compact_whitespace(title_loc.inner_text()) if title_loc.count() else ""
                    company = compact_whitespace(comp_loc.inner_text()) if comp_loc.count() else ""
                    location = compact_whitespace(loc_loc.inner_text()) if loc_loc.count() else "India"

                    candidates.append(
                        JobCandidate(
                            url=clean_url,
                            source="naukri",
                            company=company,
                            title=title,
                            location=location,
                        )
                    )
                except Exception:
                    continue
        except Exception as exc:
            self.logger.debug("Naukri listing candidate extraction error: %s", exc)
        return candidates

    def extract_job_detail(self, page: Page, candidate_url: str = "") -> JobPosting:
        url = candidate_url or page.url
        title = ""
        company = ""
        location = "India"
        description = ""

        try:
            title_loc = page.locator("h1.styles_jd-header-title__1rIE0, h1.jd-header-title, h1").first
            if title_loc.count():
                title = compact_whitespace(title_loc.inner_text())

            comp_loc = page.locator("div.styles_jd-header-comp-name__MvqAI a, div.company-name").first
            if comp_loc.count():
                company = compact_whitespace(comp_loc.inner_text())

            loc_loc = page.locator("span.styles_jdn-location__e9_sm, span.location").first
            if loc_loc.count():
                location = compact_whitespace(loc_loc.inner_text())

            desc_loc = page.locator("section.styles_job-desc-container__txpYf, div.job-description").first
            if desc_loc.count():
                description = compact_whitespace(desc_loc.inner_text())
        except Exception as exc:
            self.logger.debug("Naukri detail extraction warning: %s", exc)

        return JobPosting(
            url=url,
            source="naukri",
            title=title,
            company=company,
            location=location,
            description=description,
        )

    def expand_details(self, page: Page) -> None:
        try:
            read_more = page.locator("a:has-text('Read more'), span:has-text('Read more')").first
            if read_more.count() and read_more.is_visible():
                read_more.click(timeout=2000)
                page.wait_for_timeout(500)
        except Exception:
            pass
