from __future__ import annotations

import logging
from typing import Any
from playwright.sync_api import Page

from app.scrapers.base import BaseJobSource, JobCandidate
from app.utils import JobPosting, compact_whitespace, extract_skills_from_text


class InstahyreAdapter(BaseJobSource):
    """Adapter for extracting tech and cybersecurity jobs from Instahyre.com."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger("scrapers.instahyre")

    @property
    def source_name(self) -> str:
        return "instahyre"

    def can_handle(self, url: str) -> bool:
        lowered = (url or "").lower()
        return "instahyre.com" in lowered

    def extract_listing_candidates(self, page: Page) -> list[JobCandidate]:
        candidates: list[JobCandidate] = []
        try:
            # Instahyre job card selectors
            cards = page.locator(".employer-row, .opportunity-item, div[id^='job-']").all()
            for card in cards:
                try:
                    title_loc = card.locator(".position-name, .job-title, a[href*='/job-']").first
                    comp_loc = card.locator(".company-name, .employer-name").first
                    loc_loc = card.locator(".job-locations, .locations").first

                    url = title_loc.get_attribute("href") if title_loc.count() else ""
                    if not url:
                        continue
                    if url.startswith("/"):
                        url = f"https://www.instahyre.com{url}"
                    clean_url = url.split("?")[0]
                    title = compact_whitespace(title_loc.inner_text()) if title_loc.count() else ""
                    company = compact_whitespace(comp_loc.inner_text()) if comp_loc.count() else ""
                    location = compact_whitespace(loc_loc.inner_text()) if loc_loc.count() else "India"

                    candidates.append(
                        JobCandidate(
                            url=clean_url,
                            source="instahyre",
                            company=company,
                            title=title,
                            location=location,
                        )
                    )
                except Exception:
                    continue
        except Exception as exc:
            self.logger.debug("Instahyre candidate extraction error: %s", exc)
        return candidates

    def extract_job_detail(self, page: Page, candidate_url: str = "") -> JobPosting:
        url = candidate_url or page.url
        title = ""
        company = ""
        location = ""
        description = ""

        try:
            title_loc = page.locator("h1, .job-title, .position-title").first
            if title_loc.count():
                title = compact_whitespace(title_loc.inner_text())

            comp_loc = page.locator(".company-name, .employer-title, a[href*='/company/']").first
            if comp_loc.count():
                company = compact_whitespace(comp_loc.inner_text())

            loc_loc = page.locator(".job-locations, .location-text").first
            if loc_loc.count():
                location = compact_whitespace(loc_loc.inner_text())

            desc_loc = page.locator(".job-description, #job-description, .description-container").first
            if desc_loc.count():
                description = compact_whitespace(desc_loc.inner_text())
            else:
                body_text = page.locator("body").inner_text()
                description = compact_whitespace(body_text)[:12000]
        except Exception as exc:
            self.logger.debug("Instahyre detail extraction error: %s", exc)

        return JobPosting(
            source="instahyre",
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
            read_more = page.locator("button:has-text('Read More'), a:has-text('Read more')").first
            if read_more.count() and read_more.is_visible():
                read_more.click()
                page.wait_for_timeout(500)
        except Exception:
            pass
