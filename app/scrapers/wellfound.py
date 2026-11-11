from __future__ import annotations

import logging
from typing import Any
from playwright.sync_api import Page

from app.scrapers.base import BaseJobSource, JobCandidate
from app.utils import JobPosting, compact_whitespace, extract_skills_from_text


class WellfoundAdapter(BaseJobSource):
    """Adapter for extracting tech startup & remote security jobs from Wellfound (AngelList)."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger("scrapers.wellfound")

    @property
    def source_name(self) -> str:
        return "wellfound"

    def can_handle(self, url: str) -> bool:
        lowered = (url or "").lower()
        return "wellfound.com" in lowered or "angel.co" in lowered

    def extract_listing_candidates(self, page: Page) -> list[JobCandidate]:
        candidates: list[JobCandidate] = []
        try:
            cards = page.locator("div[data-test='StartupResult'], div[class*='styles_jobListing']").all()
            for card in cards:
                try:
                    title_loc = card.locator("a[href*='/jobs/'], h2, h3").first
                    comp_loc = card.locator("a[href*='/company/'], h4").first
                    loc_loc = card.locator("span[class*='location'], span:has-text('Remote')").first

                    url = title_loc.get_attribute("href") if title_loc.count() else ""
                    if not url:
                        continue
                    if url.startswith("/"):
                        url = f"https://wellfound.com{url}"
                    clean_url = url.split("?")[0]
                    title = compact_whitespace(title_loc.inner_text()) if title_loc.count() else ""
                    company = compact_whitespace(comp_loc.inner_text()) if comp_loc.count() else ""
                    location = compact_whitespace(loc_loc.inner_text()) if loc_loc.count() else "Remote"

                    candidates.append(
                        JobCandidate(
                            url=clean_url,
                            source="wellfound",
                            company=company,
                            title=title,
                            location=location,
                        )
                    )
                except Exception:
                    continue
        except Exception as exc:
            self.logger.debug("Wellfound candidate extraction error: %s", exc)
        return candidates

    def extract_job_detail(self, page: Page, candidate_url: str = "") -> JobPosting:
        url = candidate_url or page.url
        title = ""
        company = ""
        location = ""
        description = ""

        try:
            title_loc = page.locator("h1").first
            if title_loc.count():
                title = compact_whitespace(title_loc.inner_text())

            comp_loc = page.locator("a[href*='/company/']").first
            if comp_loc.count():
                company = compact_whitespace(comp_loc.inner_text())

            desc_loc = page.locator("div[data-test='JobDescription'], div[class*='description']").first
            if desc_loc.count():
                description = compact_whitespace(desc_loc.inner_text())
            else:
                body_text = page.locator("body").inner_text()
                description = compact_whitespace(body_text)[:12000]
        except Exception as exc:
            self.logger.debug("Wellfound detail extraction error: %s", exc)

        return JobPosting(
            source="wellfound",
            company=company,
            title=title,
            url=url,
            location=location or "Remote",
            skills=extract_skills_from_text(f"{title} {description}"),
            criteria_text=description[:5000],
            description=description,
        )

    def expand_details(self, page: Page) -> None:
        try:
            read_more = page.locator("button:has-text('Read more'), button:has-text('View more')").first
            if read_more.count() and read_more.is_visible():
                read_more.click()
                page.wait_for_timeout(500)
        except Exception:
            pass
