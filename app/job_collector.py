from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
from playwright.sync_api import Page

from app.utils import (
    DISALLOWED_JOB_KEYWORDS,
    TARGET_ROLE_KEYWORDS,
    JobPosting,
    compact_whitespace,
    detect_source_from_url,
    domain_from_url,
    extract_skills_from_text,
    normalize_key,
    unique_list,
)

DOM_EXPAND_JS = """
() => {
  const unsafe = /(apply|submit|send|save|share|follow|sign\\s*in|login|register|create\\s*alert|easy\\s*apply|more\\s*options|tailor\\s*my\\s*resume|use\\s*ai|for\\s*business|^me$|^help$|report|imposter|fraud|suspicious|fake job|fake recruiter|flag this)/i;
  const positive = /(show\\s*more|read\\s*more|see\\s*more|view\\s*more|more\\s*details|full\\s*description|requirements|responsibilities|qualifications|eligibility|criteria|skills|benefits|about\\s*company|company\\s*details|job\\s*profile|role\\s*profile|recruiter|contact|email|phone|application\\s*process|how\\s*to\\s*apply|expand|accordion|collapse|details|\\.\\.\\.\\s*more)/i;
  const safeApplyContext = /(how\\s*to\\s*apply|application\\s*process|contact|email|phone|recruiter)/i;
  const textOf = (el) => [
    el.innerText,
    el.textContent,
    el.getAttribute("aria-label"),
    el.getAttribute("title"),
    el.getAttribute("data-control-name"),
    el.getAttribute("class"),
    el.getAttribute("id")
  ].filter(Boolean).join(" ").replace(/\\s+/g, " ").trim();
  const isVisible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return !!(rect.width || rect.height) && style.visibility !== "hidden" && style.display !== "none";
  };
  const isSafeAnchor = (el) => {
    if (el.tagName && el.tagName.toLowerCase() === "a") {
        const href = (el.getAttribute("href") || "").trim().toLowerCase();
        if (href !== "" && href !== "#" && !href.startsWith("javascript:")) return false;
    }
    return true;
  };
  
  let clicked = 0;
  const labels = [];
  const seen = new Set();
  
  const clickElement = (el, label) => {
    if (!el || clicked >= 15 || seen.has(el)) return false;
    seen.add(el);
    if (!isVisible(el)) return false;
    if (!isSafeAnchor(el)) return false;
    if (!positive.test(label) || (unsafe.test(label) && !safeApplyContext.test(label))) return false;
    
    try {
      el.scrollIntoView({ block: "center", inline: "center" });
      el.click();
      clicked += 1;
      labels.push(`${el.tagName.toLowerCase()}:${label.slice(0, 50)}`);
      return true;
    } catch (error) {
      return false;
    }
  };

  const selectors = [
    "button", "a", "summary", "[role='button']",
    "[class*='expand' i]", "[class*='accordion' i]",
    "[class*='collapse' i]", "[id*='expand' i]"
  ];
  
  for (const selector of selectors) {
    for (const el of document.querySelectorAll(selector)) {
      clickElement(el, textOf(el));
    }
  }
  
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (clicked < 15 && walker.nextNode()) {
    const text = (walker.currentNode.nodeValue || "").replace(/\\s+/g, " ").trim();
    if (!positive.test(text) || (unsafe.test(text) && !safeApplyContext.test(text))) continue;
    
    const parent = walker.currentNode.parentElement;
    if (!parent) continue;
    const clickable = parent.closest("button, [role='button'], a, span, div, p");
    if (clickable) {
      clickElement(clickable, text);
    }
  }
  
  return { clicked, candidates: seen.size, labels };
}
"""

LINKEDIN_JOB_POST_HINTS = {
    "apply",
    "career",
    "hiring",
    "job",
    "jobs",
    "opening",
    "openings",
    "opportunity",
    "recruiting",
    "role",
    "roles",
    "vacancy",
    "we are hiring",
    "we're hiring",
}

APPLICATION_HOST_HINTS = (
    "ashbyhq.com",
    "greenhouse.io",
    "jobs.lever.co",
    "myworkdayjobs.com",
    "smartrecruiters.com",
    "successfactors",
    "zohorecruit",
)

APPLICATION_PATH_HINTS = (
    "apply",
    "career",
    "careers",
    "job",
    "jobs",
    "opening",
    "positions",
    "recruit",
    "vacancy",
)

BLOCKED_APPLICATION_URL_MARKERS = (
    "facebook.com/",
    "instagram.com/",
    "linkedin.com/company/",
    "linkedin.com/feed/",
    "linkedin.com/in/",
    "linkedin.com/posts/",
    "linkedin.com/pulse/",
    "linkedin.com/school/",
    "/imposter/",
    "report-fake-job",
    "fake-job-recruiter",
    "report-fake-recruiter",
    "jd_warning",
    "t.me/",
    "telegram.me/",
    "twitter.com/",
    "wa.me/",
    "whatsapp.com/",
    "x.com/",
    "youtube.com/",
    "youtu.be/",
)


class JobCollector:
    def __init__(self, logger) -> None:
        self.logger = logger
        from app.scrapers import (
            NaukriAdapter,
            LinkedInJobsAdapter,
            CompanyATSAdapter,
            InstahyreAdapter,
            FounditAdapter,
            WellfoundAdapter,
        )
        self.adapters = [
            LinkedInJobsAdapter(self.logger),
            NaukriAdapter(self.logger),
            InstahyreAdapter(self.logger),
            FounditAdapter(self.logger),
            WellfoundAdapter(self.logger),
            CompanyATSAdapter(self.logger),
        ]

    def get_adapter(self, url: str):
        """Locate the modular strategy adapter capable of scraping this URL."""
        for adapter in self.adapters:
            if adapter.can_handle(url):
                return adapter
        return None

    def read_urls(self, input_path: Path) -> list[str]:
        lines = input_path.read_text(encoding="utf-8").splitlines()
        urls = [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
        return unique_list(urls)

    def is_listing_seed_url(self, url: str) -> bool:
        lowered = url.lower()
        source = detect_source_from_url(lowered)
        if source == "linkedin":
            return (
                ("/jobs/" in lowered and "/jobs/view/" not in lowered)
                or "/search/results/content/" in lowered
                or "/search/results/posts/" in lowered
            )
        if source == "naukri":
            return "job-listings" not in lowered and any(
                marker in lowered for marker in ("?k=", "&k=", "-jobs", "/jobs", "naukri.com/")
            )
        return False

    def page_needs_manual_login(self, page: Page) -> bool:
        lowered_url = page.url.lower()
        if any(marker in lowered_url for marker in ("login", "signin", "authwall", "checkpoint", "/uas/")):
            return True

        # Valid listing search pages (LinkedIn /jobs/search, Naukri search) allow unauthenticated discovery;
        # passive footer login drawers or sign-in promos do NOT block listing scraping.
        if self.is_listing_seed_url(page.url):
            return False

        try:
            body_text = compact_whitespace(page.locator("body").inner_text(timeout=5000)).lower()
        except Exception:  # noqa: BLE001
            return False

        # Exclude LinkedIn guest drawer password fields from false auth triggers
        has_active_pw = (
            page.locator("input[type='password']:not(#session_password):not([name='session_password'])").count() > 0
            if "linkedin.com" in lowered_url
            else page.locator("input[type='password']").count() > 0
        )

        login_indicators = (
            "sign in with google",
            "continue with google",
            "login to continue",
            "log in to continue",
            "sign in to continue",
            "sign in to view",
            "log in to view",
        )
        return has_active_pw or any(
            indicator in body_text for indicator in login_indicators
        )

    def discover_job_urls(self, page: Page, target_roles: list[str] | None, max_results: int = 15) -> list[str]:
        candidates = self.discover_job_candidates(page, target_roles, max_results=max_results)
        return unique_list([candidate["url"] for candidate in candidates if candidate.get("url")])

    def discover_job_candidates(
        self,
        page: Page,
        target_roles: list[str] | None,
        max_results: int = 15,
    ) -> list[dict[str, str]]:
        current_url = page.url
        if not self.is_listing_seed_url(current_url):
            canonical = self._canonical_job_url(current_url)
            return [{"url": canonical or current_url, "company": "", "title": ""}]

        # Strategy Pattern: Delegate to specialized adapter if available
        adapter = self.get_adapter(current_url)
        if adapter and not self._is_linkedin_content_search(current_url):
            try:
                extracted = adapter.extract_listing_candidates(page)
                if extracted:
                    candidates = [{"url": c.url, "company": c.company, "title": c.title} for c in extracted[:max_results]]
                    self.logger.info("Discovered %d candidate jobs via %s adapter", len(candidates), adapter.source_name)
                    return candidates
            except Exception as ad_exc:
                self.logger.debug("Adapter %s candidate discovery fallback: %s", adapter.source_name, ad_exc)

        source = detect_source_from_url(current_url)
        requested_roles = target_roles or []
        if source == "linkedin":
            if self._is_linkedin_content_search(current_url):
                candidates = self._extract_linkedin_post_job_candidates(page, requested_roles, max_results=max_results)
            else:
                candidates = self._extract_linkedin_listing_candidates(page, requested_roles, max_results=max_results)
        elif source == "naukri":
            candidates = self._extract_naukri_listing_candidates(page, requested_roles, max_results=max_results)
        else:
            candidates = []

        self.logger.info(
            "Discovered %s job URLs from listing page %s",
            len(candidates),
            current_url,
        )
        return candidates

    @staticmethod
    def is_non_job_content_url(url: str) -> bool:
        lowered = (url or "").lower()
        if "linkedin.com" in lowered:
            # Valid jobs search and collection listing URLs should never be classified as non-job content
            if "/jobs/search" in lowered or "/jobs/collections" in lowered:
                return False
            # Legitimate single job postings contain /jobs/view/ or currentJobId parameter
            if "linkedin.com/jobs/view/" in lowered or "/jobs/view/" in lowered or "currentjobid=" in lowered:
                return False
            # True non-job content markers on LinkedIn
            non_job_markers = (
                "/feed", "/in/", "/pulse/", "/posts/", "/company/", "/school/",
                "/learning/", "/groups/", "/messaging/", "/notifications/",
                "/mypreferences/", "/help/", "/legal/", "/events/"
            )
            if any(marker in lowered for marker in non_job_markers):
                return True
            # Any LinkedIn URL outside of /jobs/ is non-job content
            if "/jobs/" not in lowered:
                return True
        return False

    @staticmethod
    def is_blocked_application_url(url: str) -> bool:
        lowered = unquote(url or "").lower()
        return any(marker in lowered for marker in BLOCKED_APPLICATION_URL_MARKERS)

    def advance_listing_page(self, page: Page) -> bool:
        if not self.is_listing_seed_url(page.url):
            return False
        before_url = page.url
        before_text_len = self._visible_text_length(page)

        next_url = self._next_listing_href(page)
        if next_url:
            try:
                page.goto(next_url, wait_until="domcontentloaded")
                page.wait_for_timeout(2200)
                return page.url != before_url
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("Unable to navigate to next listing URL %s: %s", next_url, exc)

        patterns = (
            r"^next$",
            r"next page",
            r"view next",
            r"show next",
            r"load more",
            r"see more jobs",
        )
        unsafe = re.compile(r"apply|submit|save|share|follow|sign in|login|register|alert", re.IGNORECASE)
        for pattern in patterns:
            for role in ("button", "link"):
                try:
                    locator = page.get_by_role(role, name=re.compile(pattern, re.IGNORECASE))
                    count = min(locator.count(), 4)
                    for index in range(count):
                        item = locator.nth(index)
                        label = compact_whitespace(item.inner_text(timeout=1000) or "")
                        aria_disabled = (item.get_attribute("aria-disabled", timeout=1000) or "").lower()
                        disabled = (item.get_attribute("disabled", timeout=1000) or "").lower()
                        if unsafe.search(label) or aria_disabled == "true" or disabled:
                            continue
                        if item.is_visible() and item.is_enabled():
                            item.scroll_into_view_if_needed(timeout=1500)
                            item.click(timeout=2500)
                            page.wait_for_timeout(2500)
                            if page.url != before_url or abs(self._visible_text_length(page) - before_text_len) > 200:
                                return True
                except Exception as exc:  # noqa: BLE001
                    self.logger.debug("Unable to click listing next control %s/%s: %s", role, pattern, exc)
        return False

    def collect(self, page: Page, url: str) -> JobPosting:
        if self.is_blocked_application_url(url):
            return self._non_job_posting(url, reason="Skipped blocked social/report URL before navigation.")
        if self.is_non_job_content_url(url):
            return self._non_job_posting(url, reason="Skipped LinkedIn non-job content URL before navigation.")
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        if self.is_blocked_application_url(page.url):
            return self._non_job_posting(page.url, reason="Skipped blocked social/report URL after navigation.")
        if self.is_non_job_content_url(page.url):
            return self._non_job_posting(page.url, reason="Skipped LinkedIn non-job content URL after navigation.")
        resolved_url = self._resolve_job_detail_url(page, url)
        if self.is_blocked_application_url(resolved_url):
            return self._non_job_posting(resolved_url, reason="Skipped blocked social/report URL after resolution.")
        if self.is_non_job_content_url(resolved_url):
            return self._non_job_posting(resolved_url, reason="Skipped LinkedIn non-job content URL after resolution.")
        if resolved_url and resolved_url != page.url:
            page.goto(resolved_url, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
        if self.is_non_job_content_url(page.url):
            return self._non_job_posting(page.url, reason="Skipped LinkedIn non-job content URL before expansion.")
        expansion_summary = self._expand_job_details(page)
        final_url = self._canonical_job_url(page.url) or page.url
        if final_url != page.url:
            page.goto(final_url, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            expansion_summary = self._expand_job_details(page)
        source = detect_source_from_url(final_url)
        html = page.content()
        soup = BeautifulSoup(html, "lxml")
        raw_text = compact_whitespace(soup.get_text("\n", strip=True))
        criteria_text = self._extract_criteria_text(soup, raw_text)

        # Strategy Pattern: Delegate detail extraction to specialized adapter if available
        adapter = self.get_adapter(final_url)
        if adapter:
            try:
                adapter_posting = adapter.extract_job_detail(page, final_url)
                if adapter_posting and adapter_posting.title:
                    adapter_posting.raw_text = raw_text
                    if not adapter_posting.criteria_text:
                        adapter_posting.criteria_text = criteria_text
                    adapter_posting.expansion_audit = expansion_summary
                    if not adapter_posting.skills:
                        adapter_posting.skills = unique_list(extract_skills_from_text(raw_text))
                    self.logger.info("Collected job via adapter %s | %s @ %s", adapter.source_name, adapter_posting.title, adapter_posting.company)
                    return adapter_posting
            except Exception as ad_err:
                self.logger.debug("Adapter %s detail extraction fallback: %s", adapter.source_name, ad_err)

        if source == "linkedin":
            extracted = self._extract_linkedin(soup, raw_text, final_url)
        elif source == "naukri":
            extracted = self._extract_naukri(soup, raw_text, final_url)
        else:
            extracted = self._extract_company_page(soup, raw_text, final_url)

        posting = JobPosting(
            source=source,
            company=extracted["company"],
            title=extracted["title"],
            url=final_url,
            application_url=extracted["application_url"],
            location=extracted["location"],
            experience=extracted["experience"],
            skills=unique_list(extracted["skills"] + extract_skills_from_text(raw_text)),
            criteria_text=criteria_text,
            expansion_audit=expansion_summary,
            description=extracted["description"],
            raw_text=raw_text,
        )
        self.logger.info(
            "Collected job | source=%s | company=%s | title=%s | url=%s | expansion=%s",
            posting.source,
            posting.company,
            posting.title,
            posting.url,
            expansion_summary,
        )
        return posting

    @staticmethod
    def _non_job_posting(url: str, reason: str) -> JobPosting:
        return JobPosting(
            source=detect_source_from_url(url),
            company="",
            title="LinkedIn content/article page",
            url=url,
            application_url="",
            location="",
            experience="",
            skills=[],
            criteria_text="",
            expansion_audit=reason,
            description="",
            raw_text="",
        )

    def expand_for_actionability_check(self, page: Page) -> str:
        """Reveal apply/contact/about sections before deciding a job has no reachable action."""
        if self.is_non_job_content_url(page.url):
            return "skipped actionability expansion for LinkedIn non-job content URL"
        return self._expand_job_details(page, actionability=True)

    def refresh_current_page_job(self, page: Page, previous: JobPosting, extra_expansion_audit: str = "") -> JobPosting:
        final_url = self._canonical_job_url(page.url) or page.url
        if self.is_non_job_content_url(final_url):
            posting = self._non_job_posting(final_url, "Skipped refresh for LinkedIn non-job content URL.")
            posting.expansion_audit = compact_whitespace(f"{previous.expansion_audit} | {posting.expansion_audit}")
            return posting
        source = detect_source_from_url(final_url)
        soup = BeautifulSoup(page.content(), "lxml")
        raw_text = compact_whitespace(soup.get_text("\n", strip=True))
        criteria_text = self._extract_criteria_text(soup, raw_text)

        # Strategy Pattern: Delegate detail extraction to specialized adapter if available
        adapter = self.get_adapter(final_url)
        if adapter:
            try:
                adapter_posting = adapter.extract_job_detail(page, final_url)
                if adapter_posting and adapter_posting.title:
                    adapter_posting.raw_text = raw_text
                    if not adapter_posting.criteria_text:
                        adapter_posting.criteria_text = criteria_text
                    audit = previous.expansion_audit
                    if extra_expansion_audit:
                        audit = compact_whitespace(f"{audit} | actionability={extra_expansion_audit}")
                    adapter_posting.expansion_audit = audit
                    if not adapter_posting.skills:
                        adapter_posting.skills = unique_list(extract_skills_from_text(raw_text))
                    self.logger.info("Collected job via adapter %s | %s @ %s", adapter.source_name, adapter_posting.title, adapter_posting.company)
                    return adapter_posting
            except Exception as ad_err:
                self.logger.debug("Adapter %s detail extraction fallback: %s", adapter.source_name, ad_err)

        if source == "linkedin":
            extracted = self._extract_linkedin(soup, raw_text, final_url)
        elif source == "naukri":
            extracted = self._extract_naukri(soup, raw_text, final_url)
        else:
            extracted = self._extract_company_page(soup, raw_text, final_url)

        audit = previous.expansion_audit
        if extra_expansion_audit:
            audit = compact_whitespace(f"{audit} | actionability={extra_expansion_audit}")

        return JobPosting(
            source=source,
            company=extracted["company"] or previous.company,
            title=extracted["title"] or previous.title,
            url=final_url or previous.url,
            application_url=extracted["application_url"] or previous.application_url,
            location=extracted["location"] or previous.location,
            experience=extracted["experience"] or previous.experience,
            skills=unique_list(extracted["skills"] + previous.skills + extract_skills_from_text(raw_text)),
            criteria_text=criteria_text or previous.criteria_text,
            expansion_audit=audit,
            description=extracted["description"] or previous.description,
            raw_text=raw_text or previous.raw_text,
        )

    def _resolve_job_detail_url(self, page: Page, requested_url: str) -> str:
        current_url = page.url or requested_url
        canonical = self._canonical_job_url(current_url) or self._canonical_job_url(requested_url)
        if canonical:
            return canonical

        if not self.is_listing_seed_url(current_url):
            return current_url

        candidates = self.discover_job_candidates(page, target_roles=None, max_results=1)
        if candidates:
            return candidates[0].get("url", "") or current_url
        return current_url

    def collect_company_context(self, page: Page, url: str) -> str:
        if self.is_blocked_application_url(url):
            self.logger.info("Skipping blocked non-application URL: %s", url)
            return ""
        if self.is_non_job_content_url(url):
            self.logger.info("Skipping company-context collection for LinkedIn non-job content URL: %s", url)
            return ""
        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            if self.is_blocked_application_url(page.url):
                self.logger.info("Skipping company-context expansion after landing on blocked non-application URL: %s", page.url)
                return ""
            if self.is_non_job_content_url(page.url):
                self.logger.info("Skipping company-context expansion after landing on LinkedIn non-job content URL: %s", page.url)
                return ""
            self._expand_job_details(page)
            soup = BeautifulSoup(page.content(), "lxml")
            return self._extract_criteria_text(soup, compact_whitespace(soup.get_text("\n", strip=True)))
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Unable to collect company-site criteria from %s: %s", url, exc)
            return ""

    @staticmethod
    def _extract_linkedin_job_id(url: str) -> str:
        lowered = unquote(url).lower()
        match = re.search(r"/jobs/view/(\d+)", lowered)
        if match:
            return match.group(1)
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        for key in ("referenceJobId", "currentJobId", "jobId"):
            value = (query.get(key) or [""])[0]
            if value.isdigit():
                return value
        return ""

    @classmethod
    def _canonical_job_url(cls, url: str) -> str:
        lowered = unquote(url).lower()
        source = detect_source_from_url(lowered)

        if source == "linkedin":
            job_id = cls._extract_linkedin_job_id(url)
            if job_id:
                return f"https://www.linkedin.com/jobs/view/{job_id}/"
            if any(marker in lowered for marker in ("/feed/update/", "/company/", "/search/results/", "/jobs/search/")):
                return ""
            return url.split("?")[0]

        if source == "naukri":
            if "job-listings-" in lowered:
                return url.split("?")[0]
            return ""

        return url

    def _extract_linkedin(self, soup: BeautifulSoup, raw_text: str, url: str) -> dict:
        return {
            "title": self._first_text(
                soup,
                [
                    "h1.t-24",
                    "h1.top-card-layout__title",
                    ".job-details-jobs-unified-top-card__job-title h1",
                    "h1",
                ],
            ),
            "company": self._first_text(
                soup,
                [
                    ".job-details-jobs-unified-top-card__company-name",
                    ".topcard__org-name-link",
                    "a.topcard__org-name-link",
                ],
            ),
            "location": self._first_text(
                soup,
                [
                    ".job-details-jobs-unified-top-card__bullet",
                    ".topcard__flavor--bullet",
                    ".jobs-unified-top-card__primary-description-container",
                ],
            ),
            "experience": self._experience_from_text(raw_text),
            "skills": self._skills_from_badges(
                soup,
                [
                    ".job-details-skill-match-status-list__skill",
                    "a[href*='skills']",
                    "span[class*='skill']",
                ],
            ),
            "description": self._first_text(
                soup,
                [
                    ".jobs-description__content",
                    ".show-more-less-html__markup",
                    ".description__text",
                ],
            )
            or raw_text,
            "application_url": self._first_href(
                soup,
                ["a[href*='linkedin.com/jobs/view']", "a[href*='apply']"],
                default=url,
            ),
        }

    def _extract_naukri(self, soup: BeautifulSoup, raw_text: str, url: str) -> dict:
        return {
            "title": self._first_text(
                soup,
                [
                    "h1[class*='jd-header-title']",
                    "h1.styles_jd-header-title__",
                    "h1",
                ],
            ),
            "company": self._first_text(
                soup,
                [
                    "a[class*='comp-name']",
                    "div[class*='company'] a",
                    "div[class*='comp-name']",
                ],
            ),
            "location": self._first_text(
                soup,
                [
                    "span[class*='location']",
                    "div[class*='location']",
                    "div.styles_jhc__location__",
                ],
            ),
            "experience": self._first_text(
                soup,
                [
                    "span[class*='experience']",
                    "div[class*='experience']",
                ],
            )
            or self._experience_from_text(raw_text),
            "skills": self._skills_from_badges(
                soup,
                [
                    "a[class*='chip']",
                    "span[class*='tag']",
                    "div[class*='key-skill'] a",
                ],
            ),
            "description": self._first_text(
                soup,
                [
                    "section[class*='job-desc']",
                    "div[class*='dang-inner-html']",
                    "article",
                ],
            )
            or raw_text,
            "application_url": url,
        }

    def _extract_company_page(self, soup: BeautifulSoup, raw_text: str, url: str) -> dict:
        company = self._first_text(
            soup,
            [
                "meta[property='og:site_name']",
                "meta[name='application-name']",
            ],
            attr="content",
        ) or self._first_text(soup, ["header h1"])
        if not company:
            company = domain_from_url(url).split(".")[0].title()

        return {
            "title": (
                self._first_text(
                    soup,
                    [
                        "meta[property='og:title']",
                    ],
                    attr="content",
                )
                or self._first_text(
                    soup,
                    [
                        "h1",
                        "title",
                    ],
                )
                or self._title_from_page_title(soup)
            ),
            "company": company,
            "location": self._first_text(
                soup,
                [
                    "[class*='location']",
                    "[data-testid*='location']",
                ],
            ),
            "experience": self._experience_from_text(raw_text),
            "skills": self._skills_from_badges(
                soup,
                [
                    "[class*='skill']",
                    "[class*='tag']",
                    "li",
                ],
            ),
            "description": self._first_text(
                soup,
                [
                    "article",
                    "main",
                    "[class*='description']",
                ],
            )
            or raw_text,
            "application_url": self._first_href(soup, ["a[href*='apply']", "a[href*='career']"], default=url),
        }

    def _extract_linkedin_listing_urls(self, page: Page, target_roles: list[str], max_results: int) -> list[str]:
        candidates = self._extract_linkedin_listing_candidates(page, target_roles, max_results)
        return unique_list([candidate["url"] for candidate in candidates if candidate.get("url")])

    def _extract_linkedin_listing_candidates(self, page: Page, target_roles: list[str], max_results: int) -> list[dict[str, str]]:
        panel_matches = self._extract_linkedin_listing_panel_candidates(page, target_roles, max_results)
        if panel_matches:
            return panel_matches

        for _ in range(3):
            page.mouse.wheel(0, 1800)
            page.wait_for_timeout(1200)

        soup = BeautifulSoup(page.content(), "lxml")
        matches: list[dict[str, str]] = []
        for anchor in soup.select("a[href*='/jobs/view/']"):
            href = anchor.get("href", "")
            title_text = compact_whitespace(anchor.get_text(" ", strip=True))
            if not href:
                continue
            if title_text and not self._matches_target_listing(title_text, target_roles):
                continue
            full_url = self._canonical_job_url(urljoin("https://www.linkedin.com", href))
            if not full_url:
                continue
            card = anchor.find_parent(["li", "div"])
            matches.append(
                {
                    "url": full_url,
                    "company": self._company_from_linkedin_listing_card(card),
                    "title": title_text,
                }
            )
            if len(matches) >= max_results:
                break
        return self._unique_candidates(matches)

    def _extract_linkedin_listing_panel_candidates(
        self,
        page: Page,
        target_roles: list[str],
        max_results: int,
    ) -> list[dict[str, str]]:
        matches: list[dict[str, str]] = []
        selectors = (
            "li.jobs-search-results__list-item, "
            "div.job-card-container, "
            "div[data-job-id], "
            "li[data-occludable-job-id]"
        )
        try:
            cards = page.locator(selectors)
            count = min(cards.count(), max(max_results * 4, max_results))
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Unable to locate LinkedIn left-panel cards: %s", exc)
            return []

        try:
            page.evaluate('''() => {
                const selectors = [
                    '#msg-overlay', '.msg-overlay-list-bubble', '.msg-overlay-container',
                    'aside[aria-label*="message" i]', 'aside[aria-label*="messaging" i]'
                ];
                selectors.forEach(sel => document.querySelectorAll(sel).forEach(el => el.remove()));
            }''')
        except Exception:  # noqa: BLE001
            pass

        for index in range(count):
            try:
                card = cards.nth(index)
                if not card.is_visible(timeout=1000):
                    continue
                card_text = compact_whitespace(card.inner_text(timeout=1500) or "")
                if card_text and not self._matches_target_listing(card_text, target_roles):
                    continue
                card_href = self._canonical_job_url(self._href_from_locator(card))
                card.scroll_into_view_if_needed(timeout=1500)
                card.click(timeout=2500)
                page.wait_for_timeout(1800)
                soup = BeautifulSoup(page.content(), "lxml")
                raw_text = compact_whitespace(soup.get_text("\n", strip=True))
                extracted = self._extract_linkedin(soup, raw_text, page.url)
                detail_url = self._canonical_job_url(page.url) or card_href
                if not detail_url:
                    detail_url = self._first_href(soup, ["a[href*='/jobs/view/']"], default="")
                    detail_url = self._canonical_job_url(urljoin("https://www.linkedin.com", detail_url)) if detail_url else ""
                if not detail_url or not self._is_linkedin_job_view_url(detail_url):
                    continue
                title = extracted.get("title") or self._title_from_linkedin_card_text(card_text)
                if title and not self._matches_target_listing(title, target_roles):
                    continue
                matches.append(
                    {
                        "url": detail_url.split("?")[0],
                        "company": extracted.get("company") or self._company_from_linkedin_card_text(card_text),
                        "title": title,
                    }
                )
                if len(self._unique_candidates(matches)) >= max_results:
                    break
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("Unable to inspect LinkedIn result card %s: %s", index, exc)

        return self._unique_candidates(matches)[:max_results]

    def _extract_linkedin_post_job_urls(self, page: Page, target_roles: list[str], max_results: int) -> list[str]:
        candidates = self._extract_linkedin_post_job_candidates(page, target_roles, max_results)
        return unique_list([candidate["url"] for candidate in candidates if candidate.get("url")])

    def _extract_linkedin_post_job_candidates(self, page: Page, target_roles: list[str], max_results: int) -> list[dict[str, str]]:
        if not self._is_linkedin_content_search(page.url):
            self.logger.info("Skipping LinkedIn post/feed extractor outside content search: %s", page.url)
            return []
        self._ensure_linkedin_posts_sorted_latest(page)
        try:
            page.evaluate('''() => {
                const selectors = [
                    '#msg-overlay', '.msg-overlay-list-bubble', '.msg-overlay-container',
                    'aside[aria-label*="message" i]', 'aside[aria-label*="messaging" i]'
                ];
                selectors.forEach(sel => document.querySelectorAll(sel).forEach(el => el.remove()));
            }''')
        except Exception:  # noqa: BLE001
            pass

        expanded_count = 0
        for _ in range(2):
            expanded_count += self._click_linkedin_post_expanders(page)
            page.mouse.wheel(0, 1800)
            page.wait_for_timeout(1300)
        self.logger.info("Expanded LinkedIn post/feed text controls | clicked=%s | url=%s", expanded_count, page.url)

        soup = BeautifulSoup(page.content(), "lxml")
        matches: list[dict[str, str]] = []
        blocks = soup.select(
            "div.feed-shared-update-v2, li.reusable-search__result-container, div[data-urn*='activity'], article"
        )
        if not blocks:
            blocks = soup.select("main li, main div")

        for block in blocks:
            text = compact_whitespace(block.get_text(" ", strip=True))
            if not self._looks_like_linkedin_job_post(text, target_roles):
                continue

            for anchor in block.select("a[href]"):
                href = self._resolve_linkedin_href(anchor.get("href", ""))
                label = compact_whitespace(anchor.get_text(" ", strip=True))
                if not href:
                    continue
                if self._is_linkedin_noise_url(href) or self._is_linkedin_profile_or_social_url(href):
                    self.logger.debug("Skipping LinkedIn post noise/profile link | label=%s | href=%s", label, href)
                    continue
                if self._looks_like_more_info_label(label) and not self.is_non_job_content_url(href):
                    remaining = max_results - len(self._unique_candidates(matches))
                    if remaining <= 0:
                        return self._unique_candidates(matches)[:max_results]
                    matches.extend(
                        self._extract_more_info_candidates(
                            page,
                            href,
                            text,
                            target_roles,
                            max_results=remaining,
                        )
                    )
                    if len(self._unique_candidates(matches)) >= max_results:
                        return self._unique_candidates(matches)[:max_results]
                if self._is_linkedin_job_view_url(href):
                    canonical = self._canonical_job_url(href)
                    if not canonical:
                        continue
                    matches.append(
                        {
                            "url": canonical,
                            "company": self._company_from_linkedin_post_block(block),
                            "title": self._title_from_post_text(text),
                        }
                    )
                elif self._looks_like_application_url(href):
                    matches.append(
                        {
                            "url": href,
                            "company": self._company_from_application_url(href),
                            "title": self._title_from_post_text(text),
                        }
                    )
                if len(self._unique_candidates(matches)) >= max_results:
                    return self._unique_candidates(matches)[:max_results]

            for raw_url in re.findall(r"https?://[^\s<>\"]+", text):
                cleaned = raw_url.rstrip(").,;]")
                if self._is_linkedin_noise_url(cleaned):
                    continue
                if self._looks_like_application_url(cleaned):
                    matches.append(
                        {
                            "url": cleaned,
                            "company": self._company_from_application_url(cleaned),
                            "title": self._title_from_post_text(text),
                        }
                    )
                    if len(self._unique_candidates(matches)) >= max_results:
                        return self._unique_candidates(matches)[:max_results]

        return self._unique_candidates(matches)[:max_results]

    def _extract_naukri_listing_urls(self, page: Page, target_roles: list[str], max_results: int) -> list[str]:
        candidates = self._extract_naukri_listing_candidates(page, target_roles, max_results)
        return unique_list([candidate["url"] for candidate in candidates if candidate.get("url")])

    def _extract_naukri_listing_candidates(self, page: Page, target_roles: list[str], max_results: int) -> list[dict[str, str]]:
        # Remove overlays and chatbots before scraping
        try:
            page.evaluate('''() => {
                const selectors = [
                    '#chatbot', '.chatbot', '[class*="chat-container"]', '[class*="chatbot"]',
                    '#intercom-container', '#zE-Widget', '.zEWidget-launcher', '#fc_widget',
                    'iframe[id*="chat"]', 'div[class*="floating-widget"]',
                    '.overlay', '[class*="overlay"]', '[class*="modal"]', '#modal',
                ];
                selectors.forEach(sel => {
                    try { document.querySelectorAll(sel).forEach(el => el.remove()); } catch(e) {}
                });
            }''')
        except Exception:  # noqa: BLE001
            pass

        for _ in range(4):
            page.mouse.wheel(0, 1500)
            page.wait_for_timeout(1500)

        soup = BeautifulSoup(page.content(), "lxml")
        matches: list[dict[str, str]] = []
        seen_urls: set[str] = set()

        ordered_selectors = [
            "a[href*='naukri.com/job-listings']",
            "a.title[href*='naukri.com']",
            "article a[title][href]",
            "div[class*='jobTuple'] a[title][href]",
        ]

        def _add_anchor(anchor) -> bool:
            href = anchor.get("href", "")
            title_text = compact_whitespace(anchor.get("title") or anchor.get_text(" ", strip=True))
            if not href:
                return False
            if title_text and not self._matches_target_listing(title_text, target_roles):
                return False
            canonical = self._canonical_job_url(href)
            if not canonical or canonical in seen_urls:
                return False
            seen_urls.add(canonical)
            card = anchor.find_parent(["article", "div", "li"])
            matches.append(
                {
                    "url": canonical,
                    "company": self._company_from_naukri_listing_card(card),
                    "title": title_text,
                }
            )
            return True

        for selector in ordered_selectors:
            for anchor in soup.select(selector):
                _add_anchor(anchor)
                if len(matches) >= max_results:
                    return self._unique_candidates(matches)

        # Regex fallback: scan all anchors for /job-listings- in href
        if len(matches) < max_results:
            import re as _re
            _jl_pattern = _re.compile(r"/job-listings-", _re.IGNORECASE)
            for anchor in soup.find_all("a", href=True):
                if _jl_pattern.search(anchor.get("href", "")):
                    _add_anchor(anchor)
                    if len(matches) >= max_results:
                        break

        return self._unique_candidates(matches)

    def _next_listing_href(self, page: Page) -> str:
        try:
            soup = BeautifulSoup(page.content(), "lxml")
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Unable to parse listing page for next link: %s", exc)
            return ""

        selectors = [
            "a[rel='next'][href]",
            "link[rel='next'][href]",
            "a[aria-label*='next' i][href]",
            "a[title*='next' i][href]",
            "a[class*='next' i][href]",
            "a[href*='pageNo=']",
            "a[href*='start=']",
        ]
        for selector in selectors:
            for element in soup.select(selector):
                text = compact_whitespace(element.get_text(" ", strip=True) or element.get("aria-label", "") or element.get("title", ""))
                href = element.get("href", "")
                if not href:
                    continue
                if selector in {"a[href*='pageNo=']", "a[href*='start=']"} and "next" not in normalize_key(text):
                    continue
                return urljoin(page.url, href)
        return ""

    @staticmethod
    def _is_linkedin_content_search(url: str) -> bool:
        lowered = url.lower()
        return "/search/results/content/" in lowered or "/search/results/posts/" in lowered

    @classmethod
    def _unique_candidates(cls, candidates: list[dict[str, str]]) -> list[dict[str, str]]:
        seen: set[str] = set()
        ordered: list[dict[str, str]] = []
        for candidate in candidates:
            original_url = compact_whitespace(candidate.get("url", ""))
            if cls.is_blocked_application_url(original_url) or cls.is_non_job_content_url(original_url):
                continue
            canonical = cls._canonical_job_url(original_url)
            url = canonical or original_url
            if not url:
                continue
            if cls.is_blocked_application_url(url) or cls.is_non_job_content_url(url):
                continue
            key = normalize_key(url)
            if not key or key in seen:
                continue
            seen.add(key)
            ordered.append(
                {
                    "url": url,
                    "company": compact_whitespace(candidate.get("company", "")),
                    "title": compact_whitespace(candidate.get("title", "")),
                }
            )
        return ordered

    @staticmethod
    def _company_from_linkedin_listing_card(card) -> str:
        if not card:
            return ""
        selectors = [
            ".job-card-container__primary-description",
            ".job-card-container__company-name",
            ".base-search-card__subtitle",
            "h4",
        ]
        for selector in selectors:
            element = card.select_one(selector)
            if element:
                text = compact_whitespace(element.get_text(" ", strip=True))
                if text:
                    return text
        return ""

    @staticmethod
    def _href_from_locator(locator) -> str:
        for attr in ("data-job-id", "data-occludable-job-id"):
            try:
                value = locator.get_attribute(attr, timeout=1000)
                if value and value.isdigit():
                    return f"https://www.linkedin.com/jobs/view/{value}/"
            except Exception:  # noqa: BLE001
                pass
        try:
            href = locator.locator("a[href*='/jobs/view/']").first.get_attribute("href", timeout=1000)
            return urljoin("https://www.linkedin.com", href) if href else ""
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _title_from_linkedin_card_text(text: str) -> str:
        lines = [compact_whitespace(line) for line in (text or "").splitlines()]
        for line in lines:
            normalized = normalize_key(line)
            if normalized and any(normalize_key(keyword) in normalized for keyword in TARGET_ROLE_KEYWORDS):
                return line
        return lines[0] if lines else ""

    @staticmethod
    def _company_from_linkedin_card_text(text: str) -> str:
        lines = [compact_whitespace(line) for line in (text or "").splitlines() if compact_whitespace(line)]
        if len(lines) >= 2:
            return lines[1]
        return ""

    @staticmethod
    def _company_from_naukri_listing_card(card) -> str:
        if not card:
            return ""
        selectors = [
            "a[class*='comp-name']",
            "span[class*='comp-name']",
            "div[class*='comp-name']",
            "[class*='company']",
        ]
        for selector in selectors:
            element = card.select_one(selector)
            if element:
                text = compact_whitespace(element.get_text(" ", strip=True))
                if text:
                    return text
        return ""

    @staticmethod
    def _company_from_linkedin_post_block(block) -> str:
        if not block:
            return ""
        selectors = [
            ".update-components-actor__title",
            ".feed-shared-actor__title",
            ".entity-result__title-text",
            "a[href*='/company/']",
        ]
        for selector in selectors:
            element = block.select_one(selector)
            if element:
                text = compact_whitespace(element.get_text(" ", strip=True))
                text = re.sub(r"\s+2nd\s+degree.*$", "", text, flags=re.IGNORECASE).strip()
                if text:
                    return text
        return ""

    @staticmethod
    def _company_from_application_url(url: str) -> str:
        domain = domain_from_url(url).lower()
        if not domain:
            return ""
        for prefix in ("www.", "jobs.", "careers."):
            if domain.startswith(prefix):
                domain = domain[len(prefix) :]
        return domain.split(".")[0].replace("-", " ").title()

    @staticmethod
    def _title_from_post_text(text: str) -> str:
        cleaned = compact_whitespace(text)
        if not cleaned:
            return ""
        sentences = re.split(r"(?<=[.!?])\s+", cleaned)
        for sentence in sentences[:4]:
            normalized_sentence = normalize_key(sentence)
            if any(normalize_key(keyword) in normalized_sentence for keyword in TARGET_ROLE_KEYWORDS):
                return sentence[:160]
        return cleaned[:160]

    def _ensure_linkedin_posts_sorted_latest(self, page: Page) -> None:
        if not self._is_linkedin_content_search(page.url):
            return

        parsed = urlparse(page.url)
        if "date_posted" not in unquote(parsed.query).lower():
            query = parse_qs(parsed.query)
            query["sortBy"] = ['"date_posted"']
            latest_url = urlunparse(parsed._replace(query=urlencode(query, doseq=True)))
            try:
                page.goto(latest_url, wait_until="domcontentloaded")
                page.wait_for_timeout(1800)
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("Unable to reload LinkedIn content search with latest sort: %s", exc)

        try:
            body_text = compact_whitespace(page.locator("body").inner_text(timeout=3000)).lower()
            if "latest" in body_text:
                return
        except Exception:  # noqa: BLE001
            return

        # LinkedIn occasionally ignores URL params until the visible sort menu is touched.
        try:
            sort_button = page.get_by_role("button", name=re.compile(r"sort|top|latest", re.IGNORECASE)).first
            if sort_button.count() and sort_button.is_visible():
                sort_button.click(timeout=1500)
                page.wait_for_timeout(500)
                latest = page.get_by_role("button", name=re.compile(r"latest|date", re.IGNORECASE)).first
                if latest.count() and latest.is_visible():
                    latest.click(timeout=1500)
                    page.wait_for_timeout(1200)
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Unable to click LinkedIn latest sort control: %s", exc)

    def _looks_like_linkedin_job_post(self, text: str, target_roles: list[str]) -> bool:
        normalized = normalize_key(text)
        if not normalized:
            return False
        if any(normalize_key(keyword) in normalized for keyword in DISALLOWED_JOB_KEYWORDS):
            return False
        has_job_hint = any(normalize_key(hint) in normalized for hint in LINKEDIN_JOB_POST_HINTS)
        if not has_job_hint:
            return False

        target_keywords = set(TARGET_ROLE_KEYWORDS)
        target_keywords.update(normalize_key(role) for role in target_roles)
        target_keywords.update(
            {
                "api security",
                "application security",
                "cyber security",
                "cybersecurity",
                "grc",
                "information security",
                "soc",
                "vapt",
                "vulnerability assessment",
                "web security",
            }
        )
        return any(keyword in normalized for keyword in target_keywords)

    @classmethod
    def _resolve_linkedin_href(cls, href: str) -> str:
        if not href:
            return ""
        absolute = urljoin("https://www.linkedin.com", href)
        parsed = urlparse(absolute)
        query = parse_qs(parsed.query)
        for key in ("url", "u"):
            if query.get(key):
                return unquote(query[key][0])
        canonical = cls._canonical_job_url(absolute)
        return canonical or absolute

    @staticmethod
    def _is_linkedin_job_view_url(url: str) -> bool:
        return "linkedin.com/jobs/view/" in url.lower()

    @staticmethod
    def _is_linkedin_noise_url(url: str) -> bool:
        lowered = unquote(url or "").lower()
        if "linkedin.com" not in lowered:
            return False
        parsed = urlparse(lowered)
        query = parse_qs(parsed.query)
        keyword_values = " ".join(value for values in query.values() for value in values)
        return (
            "/feed/hashtag/" in lowered
            or "/hashtag/" in lowered
            or "/search/results/hashtag/" in lowered
            or "miniProfile" in url
            or "mini-profile" in lowered
            or "#job" in lowered
            or "%23job" in lowered
            or "#hiring" in lowered
            or "%23hiring" in lowered
            or normalize_key(keyword_values).startswith("job")
            or normalize_key(keyword_values).startswith("hiring")
        )

    @staticmethod
    def _is_linkedin_profile_or_social_url(url: str) -> bool:
        lowered = url.lower()
        if "linkedin.com" not in lowered:
            return False
        social_markers = (
            "/company/",
            "/feed/",
            "/groups/",
            "/in/",
            "/posts/",
            "/pulse/",
            "/school/",
            "miniProfile",
            "mini-profile",
            "/search/results/all/",
            "/search/results/people/",
            "/search/results/companies/",
            "/search/results/groups/",
        )
        return not JobCollector._is_linkedin_job_view_url(url) and any(marker.lower() in lowered for marker in social_markers)

    @staticmethod
    def _looks_like_application_url(url: str) -> bool:
        lowered = url.lower()
        if not lowered.startswith(("http://", "https://")):
            return False
        if JobCollector.is_blocked_application_url(lowered):
            return False
        if JobCollector._is_linkedin_noise_url(lowered):
            return False
        if JobCollector._is_linkedin_profile_or_social_url(lowered):
            return False

        parsed = urlparse(lowered)
        host = parsed.netloc
        path = parsed.path
        if any(hint in host for hint in APPLICATION_HOST_HINTS):
            return True
        if "linkedin.com" in host:
            return JobCollector._is_linkedin_job_view_url(lowered)
        return any(hint in path for hint in APPLICATION_PATH_HINTS)

    @staticmethod
    def _looks_like_more_info_label(label: str) -> bool:
        normalized = normalize_key(label)
        return any(
            hint in normalized
            for hint in (
                "more info",
                "learn more",
                "view job",
                "view details",
                "details",
                "open role",
                "careers",
                "apply",
            )
        )

    def _extract_more_info_candidates(
        self,
        page: Page,
        href: str,
        post_text: str,
        target_roles: list[str],
        max_results: int,
    ) -> list[dict[str, str]]:
        candidates: list[dict[str, str]] = []
        if not href.startswith(("http://", "https://")):
            return candidates
        if self._is_linkedin_noise_url(href) or self.is_non_job_content_url(href):
            self.logger.info("Skipping LinkedIn post more-info noise/non-job page: %s", href)
            return candidates
        more_page = None
        try:
            more_page = page.context.new_page()
            more_page.goto(href, wait_until="domcontentloaded", timeout=20000)
            more_page.wait_for_timeout(1800)
            if self._is_linkedin_noise_url(more_page.url) or self.is_non_job_content_url(more_page.url):
                self.logger.info("Skipping LinkedIn post more-info page after redirect to noise/non-job URL: %s", more_page.url)
                return candidates
            self._expand_job_details(more_page)
            soup = BeautifulSoup(more_page.content(), "lxml")
            raw_text = compact_whitespace(soup.get_text("\n", strip=True))
            if not self._looks_like_linkedin_job_post(f"{post_text} {raw_text}", target_roles):
                return candidates

            for anchor in soup.select("a[href]"):
                candidate_href = self._resolve_linkedin_href(anchor.get("href", ""))
                if (
                    not candidate_href
                    or self._is_linkedin_noise_url(candidate_href)
                    or self._is_linkedin_profile_or_social_url(candidate_href)
                ):
                    continue
                if self._is_linkedin_job_view_url(candidate_href) or self._looks_like_application_url(candidate_href):
                    candidates.append(
                        {
                            "url": candidate_href.split("?")[0] if self._is_linkedin_job_view_url(candidate_href) else candidate_href,
                            "company": self._company_from_application_url(candidate_href) or self._company_from_linkedin_post_block(soup),
                            "title": self._title_from_post_text(f"{post_text} {raw_text}"),
                        }
                    )
                    if len(self._unique_candidates(candidates)) >= max_results:
                        break

            if not candidates and self._looks_like_application_url(more_page.url):
                candidates.append(
                    {
                        "url": more_page.url,
                        "company": self._company_from_application_url(more_page.url),
                        "title": self._title_from_post_text(f"{post_text} {raw_text}"),
                    }
                )
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Unable to inspect LinkedIn post more-info page %s: %s", href, exc)
        finally:
            if more_page:
                try:
                    more_page.close()
                    page.bring_to_front()
                except Exception:  # noqa: BLE001
                    pass
        return self._unique_candidates(candidates)

    def _click_linkedin_post_expanders(self, page: Page) -> int:
        clicked = 0
        unsafe = re.compile(
            r"apply|submit|send|save|share|follow|sign in|login|register|create alert|more options|tailor my resume|use ai|for business|^me$|^help$",
            re.IGNORECASE,
        )
        patterns = [r"see more", r"show more", r"read more", r"view more", "^\\s*(?:\\.{3}|\\u2026)?\\s*more\\s*$", r"more"]
        for pattern in patterns:
            try:
                locator = page.get_by_role("button", name=re.compile(pattern, re.IGNORECASE))
                count = min(locator.count(), 12)
                for index in range(count):
                    item = locator.nth(index)
                    label = compact_whitespace(item.inner_text(timeout=1000) or "")
                    if unsafe.search(label):
                        continue
                    try:
                        if item.is_visible() and item.is_enabled():
                            item.click(timeout=1500)
                            page.wait_for_timeout(350)
                            clicked += 1
                    except Exception as exc:  # noqa: BLE001
                        self.logger.debug("Unable to click LinkedIn post expander %s/%s: %s", pattern, index, exc)
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("Unable to scan LinkedIn post expanders with %s: %s", pattern, exc)
        return clicked + self._click_linkedin_post_dom_expanders(page)

    def _click_linkedin_post_dom_expanders(self, page: Page) -> int:
        """Click inline LinkedIn post expanders that are not exposed as normal buttons."""
        try:
            result = page.evaluate(
                """
                () => {
                  const textOf = (el) => [
                    el.innerText,
                    el.textContent,
                    el.getAttribute("aria-label"),
                    el.getAttribute("title"),
                    el.getAttribute("class"),
                    el.getAttribute("data-test-id")
                  ].filter(Boolean).join(" ").replace(/\\s+/g, " ").trim();
                  const isVisible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return !!(rect.width || rect.height) && style.visibility !== "hidden" && style.display !== "none";
                  };
                  const positive = /(^|\\s|\\.\\.\\.|\\u2026)\\s*more\\s*$|see\\s+more|show\\s+more|read\\s+more|view\\s+more|feed-shared-inline-show-more/i;
                  const unsafe = /more\\s+options|apply|submit|send|save|share|follow|sign\\s*in|login|register|create\\s+alert|tailor\\s+my\\s+resume|use\\s+ai|for\\s+business/i;
                  const postSelector = "div.feed-shared-update-v2, li.reusable-search__result-container, div[data-urn*='activity'], article";
                  const selectors = [
                    "button",
                    "[role='button']",
                    "a[role='button']",
                    "span[aria-expanded]",
                    "button[aria-expanded]",
                    "button[aria-label*='more' i]",
                    "[aria-label*='see more' i]",
                    "[aria-label*='show more' i]",
                    "[aria-label*='read more' i]",
                    "span[class*='see-more' i]",
                    "button[class*='see-more' i]",
                    "[class*='feed-shared-inline-show-more-text' i]",
                    "[class*='show-more-less' i]",
                    "[class*='see-more-less' i]",
                    ".break-words button"
                  ];
                  const seen = new Set();
                  let clicked = 0;
                  const labels = [];
                  const clickElement = (el, label) => {
                    if (!el || clicked >= 30 || seen.has(el)) return false;
                    seen.add(el);
                    if (!isVisible(el)) return false;
                    
                    // Prevent clicking real links that cause navigation
                    if (el.tagName && el.tagName.toLowerCase() === "a") {
                        const href = (el.getAttribute("href") || "").trim().toLowerCase();
                        if (href !== "" && href !== "#" && !href.startsWith("javascript:")) {
                            return false;
                        }
                    }
                    
                    if (!el.closest(postSelector)) return false;
                    if (!positive.test(label) || unsafe.test(label)) return false;
                    try {
                      el.scrollIntoView({ block: "center", inline: "center" });
                      el.click();
                      clicked += 1;
                      labels.push(label.slice(0, 120));
                      return true;
                    } catch (error) {
                      return false;
                    }
                  };
                  for (const selector of selectors) {
                    for (const el of document.querySelectorAll(selector)) {
                      const label = textOf(el);
                      clickElement(el, label);
                    }
                  }
                  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                  while (clicked < 30 && walker.nextNode()) {
                    const text = (walker.currentNode.nodeValue || "").replace(/\\s+/g, " ").trim();
                    if (!positive.test(text) || unsafe.test(text)) continue;
                    const parent = walker.currentNode.parentElement;
                    if (!parent || !parent.closest(postSelector)) continue;
                    const clickable = parent.closest("button, [role='button'], a, span, div");
                    if (clickable) {
                      clickElement(clickable, text);
                    }
                  }
                  return { clicked, labels };
                }
                """
            )
            count = int(result.get("clicked", 0) if isinstance(result, dict) else result or 0)
            if count:
                page.wait_for_timeout(500)
                labels = result.get("labels", []) if isinstance(result, dict) else []
                self.logger.info("Clicked LinkedIn DOM post expanders | clicked=%s | labels=%s", count, "; ".join(labels[:8]))
            return count
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Unable to click LinkedIn DOM post expanders: %s", exc)
            return 0

    def _matches_target_listing(self, title: str, target_roles: list[str]) -> bool:
        normalized_title = normalize_key(title)
        if not normalized_title:
            return False

        support_fallback_keywords = {
            "desktop support",
            "it support",
            "technical support",
            "technical support engineer",
            "technical support specialist",
        }
        non_technical_support_keywords = {
            "bpo",
            "call center",
            "customer care",
            "customer service",
            "customer support",
            "inside sales",
            "sales",
            "telecaller",
            "telecalling",
            "voice process",
        }
        if any(keyword in normalized_title for keyword in support_fallback_keywords):
            return not any(keyword in normalized_title for keyword in non_technical_support_keywords)

        if any(normalize_key(keyword) in normalized_title for keyword in DISALLOWED_JOB_KEYWORDS):
            return False

        if not target_roles:
            return True

        target_keywords = set(TARGET_ROLE_KEYWORDS)
        target_keywords.update(normalize_key(role) for role in target_roles)
        target_keywords.update(
            {
                "api security",
                "application security",
                "cyber security",
                "cybersecurity",
                "grc",
                "information security",
                "soc",
                "vapt",
                "vulnerability assessment",
                "web security",
            }
        )
        import re
        for keyword in target_keywords:
            if re.search(r'\b' + re.escape(keyword) + r'(?:\b|s\b)', normalized_title):
                return True
        return False

    def _expand_naukri_description(self, page: Page) -> int:
        """Click 'read more' inside the Naukri job description section to expand it."""
        try:
            container = page.locator("section[class*='job-desc']").first
            if container.count() == 0:
                return 0
            clicked = 0
            for tag in ("a", "button"):
                elems = container.locator(tag).all()
                for elem in elems:
                    try:
                        text = (elem.inner_text() or "").strip().lower()
                        if text == "read more":
                            elem.click()
                            page.wait_for_timeout(1000)
                            clicked += 1
                    except Exception:  # noqa: BLE001
                        continue
            return clicked
        except Exception:  # noqa: BLE001
            return 0

    def _expand_linkedin_description(self, page: Page) -> int:
        """Click 'show more' / 'see more' inside the LinkedIn job description container."""
        try:
            container = page.locator(
                ".jobs-description__container, .show-more-less-html"
            ).first
            if container.count() == 0:
                return 0
            clicked = 0
            show_more_patterns = {"...see more", "show more", "... more", "see more"}
            for tag in ("button", "span", "a"):
                elems = container.locator(tag).all()
                for elem in elems:
                    try:
                        text = (elem.inner_text() or "").strip().lower()
                        if text in show_more_patterns:
                            elem.click()
                            page.wait_for_timeout(800)
                            clicked += 1
                    except Exception:  # noqa: BLE001
                        continue
            return clicked
        except Exception:  # noqa: BLE001
            return 0

    def _expand_job_details(self, page: Page, actionability: bool = False) -> str:
        try:
            page.evaluate('''() => {
                const selectors = [
                    '#msg-overlay', '.msg-overlay-list-bubble', '.msg-overlay-container',
                    'aside[aria-label*="message" i]', 'aside[aria-label*="messaging" i]',
                    '#chatbot', '.chatbot', '[class*="chat-container"]', '[class*="chatbot"]',
                    '#intercom-container', '#zE-Widget', '.zEWidget-launcher', '#fc_widget',
                    'iframe[id*="chat"]', 'div[class*="floating-widget"]',
                    '.artdeco-global-alert-container', '.global-alert', '[class*="global-alert"]',
                    '.notification-badge', '[class*="banner--warning"]', '[class*="alert-banner"]',
                    '[data-view-name*="warning"]'
                ];
                selectors.forEach(sel => {
                    try { document.querySelectorAll(sel).forEach(el => el.remove()); } catch(e) {}
                });
            }''')
        except Exception:  # noqa: BLE001
            pass

        # Platform-specific targeted expansion
        naukri_expanded = self._expand_naukri_description(page)
        linkedin_expanded = self._expand_linkedin_description(page)
        clicked_total = naukri_expanded + linkedin_expanded
        expanded_text_before = self._visible_text_length(page)
        
        audit_parts: list[str] = [
            f"naukri_expanded={naukri_expanded}",
            f"linkedin_expanded={linkedin_expanded}"
        ]

        # Wait for any lazy-loaded content
        page.wait_for_timeout(1000)

        expanded_text_after = self._visible_text_length(page)
        return (
            f"clicked={clicked_total}, naukri_expanded={naukri_expanded}, linkedin_expanded={linkedin_expanded}, "
            f"before_chars={expanded_text_before}, "
            f"after_chars={expanded_text_after}, text_delta={expanded_text_after - expanded_text_before}, "
            f"actions={' | '.join(audit_parts[:8]) or 'none'}"
        )

    def _click_dom_expand_controls(self, page: Page) -> tuple[int, str]:
        try:
            pages_before = list(page.context.pages)
            result = page.evaluate(DOM_EXPAND_JS)
            page.wait_for_timeout(900)
            self._close_tabs_opened_during_expansion(page, pages_before)
            labels = result.get("labels", []) if isinstance(result, dict) else []
            clicked = int(result.get("clicked", 0)) if isinstance(result, dict) else 0
            candidates = int(result.get("candidates", 0)) if isinstance(result, dict) else 0
            return clicked, f"clicked={clicked}, candidates={candidates}, labels={'; '.join(labels[:5])}"
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Unable to run DOM expansion pass: %s", exc)
            return 0, f"failed={exc}"

    def _close_tabs_opened_during_expansion(self, page: Page, pages_before: list[Page]) -> None:
        """Expansion clicks are only meant to toggle in-page content, never navigate. Close any
        tab that opened anyway (e.g. an anchor that slipped past the safety filters) immediately,
        rather than letting it accumulate across the up-to-5 expansion passes run per job."""
        try:
            for candidate_page in list(page.context.pages):
                if candidate_page is page or candidate_page in pages_before or candidate_page.is_closed():
                    continue
                self.logger.info("Closing unexpected tab opened during expansion click: %s", candidate_page.url)
                candidate_page.close()
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Unable to close tabs opened during expansion: %s", exc)

    def _click_expand_controls(self, page: Page, actionability: bool = False) -> int:
        clicked = 0
        patterns = [
            r"show more",
            r"read more",
            r"see more",
            r"view more",
            r"more details",
            r"\.\.\.\s*more",
            r"show full description",
            r"more about",
            r"job description",
            r"requirements",
            r"responsibilities",
            r"qualifications",
            r"eligibility",
            r"criteria",
            r"skills",
            r"benefits",
            r"expand",
            r"open",
            r"show",
        ]
        if actionability:
            patterns.extend(
                [
                    r"about company",
                    r"about the company",
                    r"company details",
                    r"company profile",
                    r"job profile",
                    r"role profile",
                    r"profile summary",
                    r"recruiter details",
                    r"recruiter",
                    r"contact",
                    r"contact details",
                    r"email",
                    r"phone",
                    r"application process",
                    r"how to apply",
                ]
            )
        unsafe = re.compile(
            r"apply|submit|send|save|share|follow|sign in|login|register|create alert|more options|tailor my resume|use ai|for business|^me$|^help$",
            re.IGNORECASE,
        )
        for pattern in patterns:
            for role in ("button", "link"):
                try:
                    locator = page.get_by_role(role, name=re.compile(pattern, re.IGNORECASE))
                    count = min(locator.count(), 4)
                    for index in range(count):
                        item = locator.nth(index)
                        label = compact_whitespace(item.inner_text(timeout=1000) or "")
                        if unsafe.search(label) and not self._is_safe_actionability_expander(label):
                            continue
                        try:
                            if item.is_visible() and item.is_enabled():
                                if role == "link":
                                    href = item.get_attribute("href", timeout=1000)
                                    if href and href != "#" and not href.startswith("javascript:"):
                                        continue
                                item.click(timeout=1500)
                                page.wait_for_timeout(500)
                                clicked += 1
                        except Exception as exc:  # noqa: BLE001
                            self.logger.debug("Unable to click expander %s/%s/%s: %s", role, pattern, index, exc)
                except Exception as exc:  # noqa: BLE001
                    self.logger.debug("Unable to scan expanders with %s/%s: %s", role, pattern, exc)

        try:
            summaries = page.locator("summary")
            count = min(summaries.count(), 4)
            for index in range(count):
                item = summaries.nth(index)
                label = compact_whitespace(item.inner_text(timeout=1000) or "")
                if unsafe.search(label) and not self._is_safe_actionability_expander(label):
                    continue
                if item.is_visible():
                    item.click(timeout=1500)
                    page.wait_for_timeout(500)
                    clicked += 1
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Unable to scan summary expanders: %s", exc)
        return clicked

    @staticmethod
    def _is_safe_actionability_expander(label: str) -> bool:
        normalized = normalize_key(label)
        return any(
            marker in normalized
            for marker in (
                "how to apply",
                "application process",
                "contact",
                "contact details",
                "email",
                "phone",
                "recruiter",
            )
        )

    @staticmethod
    def _scroll_page_for_lazy_sections(page: Page) -> None:
        for _ in range(2):
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(700)
        page.mouse.wheel(0, -3600)
        page.wait_for_timeout(700)

    @staticmethod
    def _visible_text_length(page: Page) -> int:
        try:
            return len(compact_whitespace(page.locator("body").inner_text(timeout=3000)))
        except Exception:  # noqa: BLE001
            return 0

    def _extract_criteria_text(self, soup: BeautifulSoup, raw_text: str) -> str:
        criteria_selectors = [
            "[class*='description']",
            "[class*='job-desc']",
            "[class*='requirements']",
            "[class*='qualification']",
            "[class*='criteria']",
            "[class*='responsibilities']",
            "[class*='skills']",
            "[data-testid*='description']",
            "[data-testid*='requirements']",
            "section",
            "article",
            "main",
        ]
        chunks: list[str] = []
        for selector in criteria_selectors:
            for element in soup.select(selector):
                text = compact_whitespace(element.get_text(" ", strip=True))
                if self._looks_like_criteria_text(text):
                    chunks.append(text)
        if not chunks:
            chunks.append(raw_text)
        return "\n".join(unique_list(chunks))[:12000]

    @staticmethod
    def _looks_like_criteria_text(text: str) -> bool:
        if len(text) < 80:
            return False
        lowered = normalize_key(text)
        signals = (
            "experience",
            "responsibilities",
            "requirements",
            "qualification",
            "skills",
            "eligibility",
            "criteria",
            "must have",
            "good to have",
            "role",
            "job description",
        )
        return any(signal in lowered for signal in signals)

    @staticmethod
    def _first_text(
        soup: BeautifulSoup,
        selectors: list[str],
        attr: str | None = None,
    ) -> str:
        for selector in selectors:
            element = soup.select_one(selector)
            if not element:
                continue
            if attr:
                value = element.get(attr, "")
            else:
                value = element.get_text(" ", strip=True)
            value = compact_whitespace(value)
            if value:
                return value
        return ""

    @staticmethod
    def _first_href(soup: BeautifulSoup, selectors: list[str], default: str) -> str:
        for selector in selectors:
            element = soup.select_one(selector)
            if element and element.get("href"):
                href = element["href"]
                if JobCollector.is_blocked_application_url(href):
                    continue
                return href
        return default

    @staticmethod
    def _skills_from_badges(soup: BeautifulSoup, selectors: list[str]) -> list[str]:
        hits: list[str] = []
        for selector in selectors:
            for element in soup.select(selector):
                text = compact_whitespace(element.get_text(" ", strip=True))
                if 2 <= len(text) <= 50:
                    hits.append(text)
        return unique_list(hits[:20])

    @staticmethod
    def _experience_from_text(text: str) -> str:
        lowered = text.lower()
        for marker in ("years of experience", "experience", "exp"):
            index = lowered.find(marker)
            if index == -1:
                continue
            chunk = text[max(0, index - 40) : index + 80]
            if any(char.isdigit() for char in chunk):
                return compact_whitespace(chunk)
        return ""

    @staticmethod
    def _title_from_page_title(soup: BeautifulSoup) -> str:
        title = soup.title.string if soup.title and soup.title.string else ""
        return compact_whitespace(title)
