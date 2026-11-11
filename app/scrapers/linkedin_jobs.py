from __future__ import annotations

import logging
import re
from typing import Any
from playwright.sync_api import Page

from app.scrapers.base import BaseJobSource, JobCandidate
from app.utils import JobPosting, compact_whitespace


class LinkedInJobsAdapter(BaseJobSource):
    """Adapter for extracting job listings and details from LinkedIn Jobs."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger("scrapers.linkedin")

    @property
    def source_name(self) -> str:
        return "linkedin"

    def can_handle(self, url: str) -> bool:
        lowered = (url or "").lower()
        return "linkedin.com/jobs" in lowered

    def extract_listing_candidates(self, page: Page) -> list[JobCandidate]:
        candidates: list[JobCandidate] = []
        try:
            cards = page.locator("div.job-card-container, li.jobs-search-results__list-item").all()
            for card in cards:
                try:
                    title_loc = card.locator("a.job-card-list__title, a.job-card-container__link").first
                    comp_loc = card.locator(".job-card-container__primary-description, .artdeco-entity-lockup__subtitle").first
                    loc_loc = card.locator(".job-card-container__metadata-item").first

                    url = title_loc.get_attribute("href") if title_loc.count() else ""
                    if not url:
                        continue
                    clean_url = "https://www.linkedin.com" + url.split("?")[0] if url.startswith("/") else url.split("?")[0]
                    title = compact_whitespace(title_loc.inner_text()) if title_loc.count() else ""
                    company = compact_whitespace(comp_loc.inner_text()) if comp_loc.count() else ""
                    location = compact_whitespace(loc_loc.inner_text()) if loc_loc.count() else "India"

                    candidates.append(
                        JobCandidate(
                            url=clean_url,
                            source="linkedin",
                            company=company,
                            title=title,
                            location=location,
                        )
                    )
                except Exception:
                    continue
        except Exception as exc:
            self.logger.debug("LinkedIn listing candidate extraction error: %s", exc)
        return candidates

    def extract_job_detail(self, page: Page, candidate_url: str = "") -> JobPosting:
        url = candidate_url or page.url
        title = ""
        company = ""
        location = "India"
        description = ""

        try:
            title_loc = page.locator("h1.job-details-jobs-unified-top-card__job-title, h1.top-card-layout__title, h1").first
            if title_loc.count():
                title = compact_whitespace(title_loc.inner_text())

            comp_loc = page.locator(".job-details-jobs-unified-top-card__company-name, .topcard__org-name-link").first
            if comp_loc.count():
                company = compact_whitespace(comp_loc.inner_text())

            loc_loc = page.locator(".job-details-jobs-unified-top-card__primary-description-container, .topcard__flavor--bullet").first
            if loc_loc.count():
                location = compact_whitespace(loc_loc.inner_text())

            desc_loc = page.locator("article.jobs-description__container, div.show-more-less-html__markup, #job-details").first
            if desc_loc.count():
                description = compact_whitespace(desc_loc.inner_text())
        except Exception as exc:
            self.logger.debug("LinkedIn detail extraction warning: %s", exc)

        return JobPosting(
            url=url,
            source="linkedin",
            title=title,
            company=company,
            location=location,
            description=description,
        )

    def expand_details(self, page: Page) -> None:
        try:
            see_more = page.locator("button.jobs-description__footer-button, button[aria-label*='Click to see more description']").first
            if see_more.count() and see_more.is_visible():
                see_more.click(timeout=2000)
                page.wait_for_timeout(500)
        except Exception:
            pass
