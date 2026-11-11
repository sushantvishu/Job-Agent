from __future__ import annotations

import logging
from typing import Any
from playwright.sync_api import Page

from app.scrapers.base import BaseJobSource, JobCandidate
from app.utils import JobPosting, compact_whitespace, extract_skills_from_text


class FounditAdapter(BaseJobSource):
    """Adapter for extracting job listings and details from Foundit.in (formerly Monster India)."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger("scrapers.foundit")

    @property
    def source_name(self) -> str:
        return "foundit"

    def can_handle(self, url: str) -> bool:
        lowered = (url or "").lower()
        return "foundit.in" in lowered or "monsterindia.com" in lowered

    def extract_listing_candidates(self, page: Page) -> list[JobCandidate]:
        candidates: list[JobCandidate] = []
        try:
            cards = page.locator(".srpResultCard, .jobCard, div[class*='cardContainer']").all()
            for card in cards:
                try:
                    title_loc = card.locator(".cardHead a, .jobTitle, a[href*='/job/']").first
                    comp_loc = card.locator(".companyName, .company-name").first
                    loc_loc = card.locator(".location, .loc").first

                    url = title_loc.get_attribute("href") if title_loc.count() else ""
                    if not url:
                        continue
                    if url.startswith("/"):
                        url = f"https://www.foundit.in{url}"
                    clean_url = url.split("?")[0]
                    title = compact_whitespace(title_loc.inner_text()) if title_loc.count() else ""
                    company = compact_whitespace(comp_loc.inner_text()) if comp_loc.count() else ""
                    location = compact_whitespace(loc_loc.inner_text()) if loc_loc.count() else "India"

                    candidates.append(
                        JobCandidate(
                            url=clean_url,
                            source="foundit",
                            company=company,
                            title=title,
                            location=location,
                        )
                    )
                except Exception:
                    continue
        except Exception as exc:
            self.logger.debug("Foundit listing candidate extraction error: %s", exc)
        return candidates

    def extract_job_detail(self, page: Page, candidate_url: str = "") -> JobPosting:
        url = candidate_url or page.url
        title = ""
        company = ""
        location = ""
        description = ""

        try:
            title_loc = page.locator("h1, .job-title, .jd-header-title").first
            if title_loc.count():
                title = compact_whitespace(title_loc.inner_text())

            comp_loc = page.locator(".company-name, .jd-header-comp-name").first
            if comp_loc.count():
                company = compact_whitespace(comp_loc.inner_text())

            loc_loc = page.locator(".location, .jd-header-loc").first
            if loc_loc.count():
                location = compact_whitespace(loc_loc.inner_text())

            desc_loc = page.locator(".job-description, .jd-body, #job-description").first
            if desc_loc.count():
                description = compact_whitespace(desc_loc.inner_text())
            else:
                body_text = page.locator("body").inner_text()
                description = compact_whitespace(body_text)[:12000]
        except Exception as exc:
            self.logger.debug("Foundit detail extraction error: %s", exc)

        return JobPosting(
            source="foundit",
            company=company,
            title=title,
            url=url,
            location=location or "India",
            skills=extract_skills_from_text(f"{title} {description}"),
            criteria_text=description[:5000],
            description=description,
        )

    def expand_details(self, page: Page) -> None:
        try:
            read_more = page.locator("button:has-text('Read More'), a:has-text('Read More')").first
            if read_more.count() and read_more.is_visible():
                read_more.click()
                page.wait_for_timeout(500)
        except Exception:
            pass
