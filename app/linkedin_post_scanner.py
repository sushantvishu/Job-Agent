"""
app/linkedin_post_scanner.py — Scans LinkedIn posts for cybersecurity/VAPT hiring
opportunities where the recruiter asks candidates to send resumes via email.

Flow:
1. Use Playwright with the existing browser session (already logged into LinkedIn)
2. Search LinkedIn post feed for each query keyword
3. Parse each post to extract: recruiter email, subject line, role, company, experience range
4. Filter: only accept freshers / 0-2 years experience mentions
5. Return a list of LinkedInPostLead objects for the email sender to act on

Part of the Job Agent Framework — d:/job-agent
"""
from __future__ import annotations

import hashlib
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote_plus

logger = logging.getLogger("linkedin_post_scanner")

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

# LinkedIn content/post search URL (posts, not job listings)
# Includes sortBy=date_posted and datePosted=past-month for freshness
LINKEDIN_CONTENT_SEARCH_URL = (
    "https://www.linkedin.com/search/results/content/?keywords={query}&origin=GLOBAL_SEARCH_HEADER&sortBy=%22date_posted%22&datePosted=%22past-month%22"
)

# Cybersecurity / VAPT fresher-specific search queries (broad + specialized)
CYBERSEC_FRESHER_QUERIES = [
    "VAPT hiring fresher send resume",
    "cybersecurity fresher hiring send CV",
    "SOC analyst fresher hiring email resume",
    "penetration testing fresher send resume",
    "cyber security internship send CV",
    "information security fresher hiring email",
    "VAPT analyst send resume hiring fresher",
    "cybersecurity analyst fresher job apply email",
    "security analyst fresher send resume email",
    "junior VAPT engineer hiring resume email",
    "application security fresher send CV email",
    "SOC analyst L1 hiring send resume",
    "bug bounty fresher hiring email resume",
    "OWASP security testing fresher send CV",
    "network security engineer fresher hiring",
    "GRC analyst fresher send resume email",
    "information security engineer fresher CV",
    "cyber security trainee send resume apply",
    "vulnerability assessment fresher hiring email",
    "ethical hacking fresher job send CV email",
    "offensive security fresher hiring",
    "incident response fresher send resume",
    "blue team analyst fresher hiring",
    "red team intern fresher send CV",
    "VAPT fresher email resume",
    "cybersecurity fresher Bangalore send resume",
    "SOC analyst fresher Bangalore email",
    "AppSec fresher hiring send resume",
    "Cyber security engineer 0-1 year send resume",
    "VAPT 1 year experience send resume",
    "Security analyst 0-2 years email resume",
    "Penetration tester immediate joiner send CV",
    "VAPT fresher Hyderabad send resume",
    "VAPT fresher Pune email resume",
    "VAPT fresher Mumbai send resume",
    "cybersecurity fresher immediate joiner send resume",
    "junior penetration tester email resume",
    "VAPT internship email resume",
    "application security engineer fresher email",
    "SOC L1 analyst 0-1 year send resume",
    "information security fresher immediate joiner",
    "VAPT analyst Delhi NCR send resume",
    "penetration tester fresher email resume",
    "VAPT 0-6 months send resume",
    "cybersecurity 0-6 months hiring email",
    "SOC analyst 0-6 months send CV",
    "VAPT 6 months experience send resume",
    "cybersecurity 6 months experience send CV",
    "SOC analyst 6 months experience email",
    "penetration testing 6 months to 1 year send resume",
    "information security 6 months 1 year send CV",
    "VAPT 1-2 years experience send resume",
    "cybersecurity 1-2 years experience send CV",
    "penetration tester 1-2 years send resume",
    "AppSec 1-2 years send resume email",
    "vulnerability assessment 1-2 years send CV",
    "ethical hacking 1-2 years email resume",
    "red team 0-1 year send resume",
    "cloud security fresher send resume email",
    "API security tester fresher send CV",
    "OWASP penetration testing send resume email",
    "cybersecurity fresher Delhi NCR send resume",
    "VAPT fresher Chennai send resume email",
]

# Regex patterns for extracting email addresses from post text
EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)

# Subject line extraction patterns
SUBJECT_PATTERNS = [
    re.compile(r"(?:subject|sub|subject line)[:\s]+[\"']?(.{5,120}?)(?:[\"']|$|\n)", re.IGNORECASE),
    re.compile(r"(?:mention in subject)[:\s]+[\"']?(.{5,120}?)(?:[\"']|$|\n)", re.IGNORECASE),
    re.compile(r"(?:use subject)[:\s]+[\"']?(.{5,120}?)(?:[\"']|$|\n)", re.IGNORECASE),
    re.compile(r"with subject[:\s]*[\"']?(.{5,120}?)(?:[\"']|$|\n|\\.)", re.IGNORECASE),
]

# Role / title extraction — look for common cybersecurity role mentions
CYBERSEC_ROLES = [
    "Application Security Analyst", "Application Security Engineer", "Application Security",
    "Vulnerability Assessment Analyst", "Network Security Analyst", "Network Security Engineer",
    "Security Operations Analyst", "Incident Response Analyst",
    "Penetration Tester", "VAPT Analyst", "VAPT Engineer", "Pen Tester",
    "SOC Analyst (L1)", "SOC Analyst L1", "SOC Analyst", "SOC Engineer",
    "Security Analyst", "Cybersecurity Analyst", "Information Security Analyst",
    "Cyber Defense Analyst", "Junior Security Analyst", "Security Engineer",
    "AppSec Engineer", "Ethical Hacker", "Red Team Analyst", "Blue Team Analyst",
    "Bug Bounty Hunter", "GRC Analyst", "Python Developer"
]

# Generic webmail domains
WEBMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "yahoo.co.in", "outlook.com", "hotmail.com",
    "icloud.com", "proton.me", "protonmail.com", "rediffmail.com", "zoho.com"
}

# Single words / generic tokens that cannot be the ENTIRE company name
EXACT_COMPANY_BLOCKLIST = {
    "application", "applications", "apply", "applying", "opportunity", "opportunities",
    "opening", "openings", "fresher", "freshers", "junior", "senior", "lead", "manager",
    "urgent", "immediate", "immediately", "joiner", "joiners", "experience", "experienced",
    "candidate", "candidates", "interview", "interviews", "resume", "resumes", "cv", "cvs",
    "cloud", "information", "cyber", "cybersecurity", "security", "vapt", "soc", "siem",
    "tools", "burp suite", "burp", "python", "linux", "we offer", "about the role",
    "your company", "our company", "the company", "hiring", "hired", "team", "our team",
    "office", "walkin", "drive", "eligibility", "delhi", "delhi ncr", "bangalore", "bengaluru",
    "mumbai", "pune", "hyderabad", "chennai", "noida", "gurgaon", "gurugram", "kolkata",
    "ahmedabad", "india", "remote", "hybrid", "full time", "part time", "intern", "internship",
    "trainee", "engineer", "analyst", "tester", "developer", "specialist", "executive",
    "responsibilities", "requirements", "skills", "qualifications", "salary", "ctc", "lpa",
    "notice period", "location", "job", "jobs", "position", "positions", "role", "roles",
    "details", "contact", "email", "mail", "send", "share", "drop", "forward", "looking",
    "seeking", "invite", "inviting", "multiple", "various", "reputed", "client", "clients",
    "mnc", "top mnc", "startup", "startups", "organization", "firm", "consultancy", "talent"
}

# Multi-word garbage phrases that should NEVER appear anywhere in a company name
GARBAGE_COMPANY_PHRASES = {
    "will be an added advantage", "is an added advantage", "is an advantage",
    "two roles in", "about the role", "we offer", "immediate joiner", "urgent requirement",
    "looking for", "our client is", "walk-in drive", "walk in drive", "endpoint security tools",
    "siem and endpoint", "eligibility criteria", "terms and conditions"
}

COMPANY_BLOCKLIST = EXACT_COMPANY_BLOCKLIST | GARBAGE_COMPANY_PHRASES

# Disqualifying experience keywords (skip if post is for senior roles)
SENIOR_KEYWORDS = [
    "3+ years", "4+ years", "5+ years", "6+ years", "7+ years",
    "8+ years", "10+ years", "senior manager", "team lead", "manager",
    "minimum 3", "minimum 4", "minimum 5", "at least 3 year",
    "at least 4 year", "at least 5 year", "3-5 year", "5-8 year",
    "3 years of experience", "4 years of experience", "5 years of experience",
]

# Qualifying fresher/junior experience keywords (0-6 months, 6m-1yr, 1-2yr)
FRESHER_KEYWORDS = [
    "fresher", "freshers", "0-6 months", "0 to 6 months", "6 months",
    "6-12 months", "6 to 12 months", "6months", "6 months - 1 year",
    "6 months to 1 year", "0-1 year", "0-1 yr", "0 to 1 year", "0 to 1 yr",
    "0-2 year", "0-2 years", "0 to 2 year", "0 to 2 years", "1-2 year",
    "1-2 years", "1 to 2 year", "1 to 2 years", "1 year", "1 yr exp",
    "less than 1", "under 1 year", "under 2 years", "below 1 year",
    "entry level", "entry-level", "junior", "trainee", "intern", "internship",
    "graduate", "recent graduate", "newly graduated", "no experience",
    "0 experience", "beginner", "campus hiring", "college graduate",
]

# Noise emails to skip (domains that are clearly not recruiter emails)
NOISE_EMAIL_DOMAINS = {
    "example.com", "gmail.com" if False else "", "test.com", "domain.com",
    "company.com", "email.com", "placeholder.com", "yourdomain.com",
    "noreply.com", "no-reply.com",
}
# Note: gmail.com is NOT excluded — candidates often post their personal gmail for resumes

# ─────────────────────────────────────────────────────────────────────────────
# Post Age Limits (Minister's Strict Rule: No posts older than 3 weeks / 21 days)
# ─────────────────────────────────────────────────────────────────────────────
AGE_REJECT_PATTERNS = [
    re.compile(r"\b(\d+)\s*(?:month|year|yr|mo)s?\s*ago\b", re.IGNORECASE),
    re.compile(r"\b(\d+)mo\s*•", re.IGNORECASE),
    re.compile(r"\b(\d+)yr?\s*•", re.IGNORECASE),
    re.compile(r"\b(\d+)y\s*•", re.IGNORECASE),
    re.compile(r"\b([4-9]|\d{2,})\s*weeks?\s*ago\b", re.IGNORECASE),
    re.compile(r"\b([4-9]|\d{2,})w\s*•", re.IGNORECASE),
    re.compile(r"\b([4-9]|\d{2,})w\b", re.IGNORECASE),
    re.compile(r"\b(2[2-9]|[3-9]\d+|\d{3,})\s*days?\s*ago\b", re.IGNORECASE),
    re.compile(r"\b(2[2-9]|[3-9]\d+|\d{3,})d\s*•", re.IGNORECASE),
]

AGE_ACCEPT_PATTERNS = [
    re.compile(r"\b([1-3])\s*weeks?\s*ago\b", re.IGNORECASE),
    re.compile(r"\b([1-3])w\s*•", re.IGNORECASE),
    re.compile(r"\b([1-3])w\b", re.IGNORECASE),
    re.compile(r"\b([1-9]|1\d|2[0-1])\s*days?\s*ago\b", re.IGNORECASE),
    re.compile(r"\b([1-9]|1\d|2[0-1])d\s*•", re.IGNORECASE),
    re.compile(r"\b([1-9]|1\d|2[0-1])d\b", re.IGNORECASE),
    re.compile(r"\b\d+\s*(?:hour|minute|min|hr|sec|second)s?\s*ago\b", re.IGNORECASE),
    re.compile(r"\b\d+[hm]\s*•", re.IGNORECASE),
    re.compile(r"\b(?:just now|today|yesterday)\b", re.IGNORECASE),
]

# Skip own email from leads
DEFAULT_OWN_EMAIL = ""


@dataclass
class LinkedInPostLead:
    """Represents a qualifying LinkedIn post with email hiring instructions."""
    post_url: str
    post_text: str
    poster_name: str
    company: str
    role: str
    email_addresses: list[str]  # where to send resume
    subject_line: str           # suggested or auto-generated
    experience_hint: str        # "fresher", "0-1 year", etc.
    skills_mentioned: list[str]
    is_fresher_eligible: bool
    post_age: str               # "2d", "1w", "3w", etc.
    raw_snippet: str
    relevance_score: int = 0


class LinkedInPostScanner:
    """
    Scans LinkedIn's content search for cybersecurity/VAPT hiring posts
    where recruiters explicitly invite candidates to email their resumes.
    """

    def __init__(self, page, logger_inst: logging.Logger | None = None, own_email: str = "") -> None:
        """
        Parameters
        ----------
        page : Playwright Page object (already logged into LinkedIn)
        """
        self.page = page
        self.logger = logger_inst or logger
        if not own_email:
            try:
                from app.config import load_config
                from app.profile_loader import load_profile
                self.own_email = load_profile(load_config().profile_path).email.lower()
            except Exception:
                self.own_email = DEFAULT_OWN_EMAIL.lower()
        else:
            self.own_email = own_email.lower()

    def scan_all_queries(
        self,
        max_pages_per_query: int = 3,
        max_posts_per_page: int = 10,
        scroll_times: int = 3,
        delay_between_queries: float = 3.0,
    ) -> list[LinkedInPostLead]:
        """
        Run all cybersecurity fresher queries across multiple pages and aggregate unique leads.

        Returns a deduplicated list of LinkedInPostLead objects.
        """
        all_leads: dict[str, LinkedInPostLead] = {}  # post_url -> lead

        for query_index, query in enumerate(CYBERSEC_FRESHER_QUERIES, start=1):
            # Recycle tab every 3 queries to purge renderer memory, DOM nodes, and Playwright CDP event listeners
            if query_index > 1 and (query_index - 1) % 3 == 0:
                try:
                    ctx = self.page.context
                    old_p = self.page
                    self.page = ctx.new_page()
                    old_p.close()
                    self.logger.info("🔄 Browser tab recycled (memory purged, fresh context established).")
                except Exception as e:
                    self.logger.debug("Tab recycling notice: %s", e)

            self.logger.info(
                "[%d/%d] Searching LinkedIn posts: %r (up to %d pages)",
                query_index, len(CYBERSEC_FRESHER_QUERIES), query, max_pages_per_query,
            )
            try:
                leads = self.scan_query(
                    query=query,
                    max_pages=max_pages_per_query,
                    max_posts_per_page=max_posts_per_page,
                    scroll_times=scroll_times,
                )
                for lead in leads:
                    if lead.post_url not in all_leads:
                        all_leads[lead.post_url] = lead

                self.logger.info(
                    "Query %r → found %d qualifying leads (total unique: %d)",
                    query, len(leads), len(all_leads),
                )
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("Error scanning query %r: %s", query, exc)
                # Attempt to recover page if a connection error occurred
                try:
                    ctx = self.page.context
                    self.page = ctx.new_page()
                except Exception:
                    pass

            if query_index < len(CYBERSEC_FRESHER_QUERIES):
                # Anti-detection: Add randomized human pause between queries
                jittered_delay = random.uniform(max(5.0, delay_between_queries * 0.8), delay_between_queries * 1.5)
                # Periodic human cool-down every 6 queries (simulate reading/reviewing results)
                if query_index % 6 == 0:
                    cooldown = random.uniform(18.0, 30.0)
                    self.logger.info("⏸️ Anti-detection cooldown: natural pause of %.1fs after query %d...", cooldown, query_index)
                    time.sleep(cooldown)
                else:
                    time.sleep(jittered_delay)

        # Sort leads strictly by relevance score (highest priority first)
        for lead in all_leads.values():
            lead.relevance_score = self.calculate_relevance_score(lead)

        sorted_leads = sorted(
            all_leads.values(),
            key=lambda l: l.relevance_score,
            reverse=True,
        )
        self.logger.info(
            "Ranked & sorted %d qualifying leads by relevance (top score: %d, min score: %d)",
            len(sorted_leads),
            sorted_leads[0].relevance_score if sorted_leads else 0,
            sorted_leads[-1].relevance_score if sorted_leads else 0,
        )
        return sorted_leads

    @staticmethod
    def calculate_relevance_score(lead: LinkedInPostLead) -> int:
        """
        Calculates a priority score (0-100+) based on experience alignment,
        cybersecurity specialization (VAPT / OWASP / AppSec), recency, and contact availability.
        """
        score = 0
        text_lower = (lead.post_text or "").lower()

        # 1. Experience alignment (Freshers to 2 years)
        if any(kw in text_lower for kw in ["0-1 year", "0 to 1", "fresher", "intern", "entry level", "trainee"]):
            score += 30
        elif any(kw in text_lower for kw in ["1-2 year", "1 to 2", "0-2 year", "0 to 2", "junior"]):
            score += 25
        else:
            score += 15

        # 2. Domain alignment check (candidate's target specialty)
        if any(kw in text_lower for kw in ["vapt", "penetration testing", "vulnerability assessment"]):
            score += 25
        if any(kw in text_lower for kw in ["owasp", "burp suite", "burp", "zap"]):
            score += 20
        if any(kw in text_lower for kw in ["api security", "appsec", "application security", "web application"]):
            score += 15
        if any(kw in text_lower for kw in ["soc", "siem", "splunk", "incident response"]):
            score += 10
        if any(kw in text_lower for kw in ["network security", "nmap", "kali linux"]):
            score += 10

        # 3. Post recency (within 3 weeks, newest prioritized first)
        age = (lead.post_age or "").lower()
        if any(kw in age for kw in ["today", "hour", "min", "just now", "1d", "2d", "3d"]):
            score += 20
        elif any(kw in age for kw in ["4d", "5d", "6d", "1w"]):
            score += 15
        elif "2w" in age:
            score += 8
        elif "3w" in age:
            score += 3

        # 4. Verified recruiter destination email present
        if lead.email_addresses:
            score += 10

        return score

    def scan_query(
        self,
        query: str,
        max_pages: int = 10,
        max_posts_per_page: int = 10,
        scroll_times: int = 3,
    ) -> list[LinkedInPostLead]:
        """
        Search for one query across up to max_pages depth (continuous scroll + pagination)
        and return all qualifying post leads.
        """
        leads: list[LinkedInPostLead] = []
        seen_lead_keys: set[str] = set()

        url = LINKEDIN_CONTENT_SEARCH_URL.format(query=quote_plus(query))
        self.logger.info("Scanning query %r (depth: up to %d pages): %s", query, max_pages, url)
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=25000)
            self.page.wait_for_timeout(2500)

            # Check if redirected to login (session expired)
            if "login" in self.page.url.lower() or "authwall" in self.page.url.lower():
                self.logger.warning("LinkedIn session expired or authwall reached for query %r.", query)
                return leads

            # Progressive scroll to load up to max_pages depth of dynamic feed updates
            total_scrolls = max(3, max_pages * 2)
            last_count = 0
            stagnant_count = 0
            actual_scrolls = 0

            for scroll_idx in range(1, total_scrolls + 1):
                actual_scrolls = scroll_idx
                # Anti-detection: Humanized smooth scrolling with randomized distances
                scroll_delta = random.randint(450, 750)
                self.page.evaluate(f"window.scrollBy({{top: {scroll_delta}, behavior: 'smooth'}})")

                # Anti-detection: Subtle mouse movements to simulate human activity
                try:
                    self.page.mouse.move(random.randint(200, 800), random.randint(250, 650))
                except Exception:
                    pass

                # Variable natural pause between scrolls
                self.page.wait_for_timeout(random.randint(1100, 2200))

                # Attempt to click "Show more results" / "See more results" if button appears
                if scroll_idx % 2 == 0:
                    try:
                        self.page.evaluate("""() => {
                            document.querySelectorAll('button').forEach(b => {
                                const t = (b.innerText || '').trim().toLowerCase();
                                if (t.includes('show more results') || t.includes('see more results') || t.includes('load more')) {
                                    try { b.click(); } catch(e) {}
                                }
                            });
                        }""")
                    except Exception:
                        pass

                # Check if new content was loaded (plateau detection)
                current_count = self.page.evaluate("document.querySelectorAll('main div').length")
                if current_count == last_count:
                    stagnant_count += 1
                    if stagnant_count >= 3 and scroll_idx >= 6:
                        self.logger.debug("Content plateau reached at scroll %d (feed end reached)", scroll_idx)
                        break
                else:
                    stagnant_count = 0
                last_count = current_count

            # Extract all post text cards up to target capacity
            total_target = max(20, max_pages * max_posts_per_page)
            post_cards = self._extract_post_cards(total_target)
            self.logger.info("Found %d post cards for query %r after %d scroll cycles", len(post_cards), query, actual_scrolls)

            for card in post_cards:
                lead = self._parse_post_card(card)
                if not lead:
                    continue

                # Key lead by primary destination email, or fall back to post url
                lead_key = lead.email_addresses[0].lower() if lead.email_addresses else lead.post_url
                if lead_key in seen_lead_keys:
                    continue
                seen_lead_keys.add(lead_key)
                leads.append(lead)

            self.logger.info("Query %r qualified %d leads (deduplicated)", query, len(leads))

        except Exception as exc:  # noqa: BLE001
            self.logger.warning("scan_query failed for %r: %s", query, exc)

        return leads

    # ------------------------------------------------------------------
    # Post card extraction from LinkedIn DOM
    # ------------------------------------------------------------------

    def _extract_post_cards(self, max_posts: int) -> list[dict[str, Any]]:
        """Extract post content from the LinkedIn content search result page."""
        cards = []

        try:
            # 1. Expand all '... more' description buttons on the page so hidden emails are revealed
            try:
                self.page.evaluate("""() => {
                    document.querySelectorAll('button').forEach(b => {
                        const t = (b.innerText || '').trim().toLowerCase();
                        if (t.includes('more') && !t.includes('all filters') && !t.includes('notifications')) {
                            try { b.click(); } catch(e) {}
                        }
                    });
                }""")
                self.page.wait_for_timeout(1000)
            except Exception:
                pass

            # 2. Modern LinkedIn DOM extraction via JavaScript evaluate:
            # Handles 2026 styled utility classes, data-urn, and Feed post markers
            js_cards = self.page.evaluate("""() => {
                const allDivs = Array.from(document.querySelectorAll('main div, [data-urn], .entity-result'));
                const postContainers = [];

                for (const div of allDivs) {
                    const text = (div.innerText || '').trim();
                    // Each genuine post container starts with 'Feed post' or has data-urn/entity-result
                    const isCandidate = text.startsWith('Feed post') || div.hasAttribute('data-urn') || div.classList.contains('entity-result');
                    if (isCandidate && text.length > 80 && text.length < 6000) {
                        const links = Array.from(div.querySelectorAll('a'))
                            .map(a => a.href)
                            .filter(h => h && (h.includes('/feed/update/') || h.includes('/posts/') || h.includes('/in/') || h.includes('/company/')));

                        postContainers.push({
                            text: text,
                            url: links[0] || '',
                            len: text.length
                        });
                    }
                }

                // Deduplicate: keep the longest unique post for each distinct author/beginning
                const unique = [];
                for (const item of postContainers) {
                    const existingIdx = unique.findIndex(u => u.text.includes(item.text) || item.text.includes(u.text));
                    if (existingIdx === -1) {
                        unique.push(item);
                    } else if (item.text.length > unique[existingIdx].text.length) {
                        unique[existingIdx] = item;
                    }
                }

                return unique.map(item => ({
                    text: item.text,
                    url: item.url,
                    time_text: '',
                    poster_name_dom: '',
                    poster_headline_dom: ''
                }));
            }""")

            if js_cards:
                processed_cards = []
                for c in js_cards:
                    text = c.get("text", "")
                    post_hash = hashlib.sha256(text[:300].encode("utf-8")).hexdigest()[:16]
                    base_url = c.get("url", "")
                    if not base_url:
                        post_url = f"https://www.linkedin.com/posts/feed-post-{post_hash}"
                    elif "#" not in base_url:
                        post_url = f"{base_url}#post-{post_hash}"
                    else:
                        post_url = base_url

                    processed_cards.append({
                        "text": text,
                        "url": post_url,
                        "time_text": c.get("time_text", ""),
                        "poster_name_dom": c.get("poster_name_dom", ""),
                        "poster_headline_dom": c.get("poster_headline_dom", ""),
                    })
                self.logger.debug("JS evaluator extracted %d post cards", len(processed_cards))
                return processed_cards[:max_posts]

            # 2. Fallback to selector-based extraction
            post_selectors = [
                ".search-results__list .entity-result",
                ".search-results-container .entity-result",
                "[data-urn]",
                ".update-components-text",
                ".occludable-update",
                ".feed-shared-update-v2",
            ]

            post_elements = []
            for selector in post_selectors:
                elements = self.page.locator(selector).all()
                if elements:
                    post_elements = elements[:max_posts]
                    self.logger.debug("Using selector %r → %d elements", selector, len(elements))
                    break

            if not post_elements:
                # Fallback: grab all text blocks that look like posts
                self.logger.debug("No post elements found with standard selectors — trying generic fallback")
                post_elements = self.page.locator("div.update-components-text, div.feed-shared-text").all()[:max_posts]

            for element in post_elements:
                try:
                    text = (element.inner_text(timeout=3000) or "").strip()
                    # Extract relative time / post age string from LinkedIn DOM
                    time_text = ""
                    try:
                        time_el = element.locator(
                            "time, span.visually-hidden, span.update-components-actor__sub-description, .feed-shared-actor__sub-description"
                        ).first
                        time_text = (time_el.inner_text(timeout=1000) or "").strip()
                    except Exception:
                        pass

                    # Extract poster name and headline from DOM
                    poster_name = ""
                    poster_headline = ""
                    try:
                        name_el = element.locator(
                            ".update-components-actor__name span[aria-hidden='true'], .feed-shared-actor__name, span.feed-shared-actor__name"
                        ).first
                        poster_name = (name_el.inner_text(timeout=1000) or "").strip()
                    except Exception:
                        pass

                    try:
                        desc_el = element.locator(
                            ".update-components-actor__description, .feed-shared-actor__description"
                        ).first
                        poster_headline = (desc_el.inner_text(timeout=1000) or "").strip()
                    except Exception:
                        pass

                    # Try to get the post URL (permalink)
                    try:
                        post_link = element.locator("a[href*='/posts/'], a[href*='/feed/update/']").first
                        href = post_link.get_attribute("href", timeout=2000) or ""
                    except Exception:
                        href = self.page.url  # fallback to search page url

                    if text and len(text) > 50:
                        cards.append({
                            "text": text,
                            "url": href or self.page.url,
                            "time_text": time_text,
                            "poster_name_dom": poster_name,
                            "poster_headline_dom": poster_headline,
                        })
                except Exception:  # noqa: BLE001
                    continue

        except Exception as exc:  # noqa: BLE001
            self.logger.debug("_extract_post_cards error: %s", exc)

        return cards

    # ------------------------------------------------------------------
    # Post parsing logic
    # ------------------------------------------------------------------

    def _parse_post_card(self, card: dict[str, Any]) -> LinkedInPostLead | None:
        """Parse a post card dict into a LinkedInPostLead if it qualifies."""
        text = card.get("text", "")
        post_url = card.get("url", "")

        if not text or len(text) < 30:
            return None

        text_lower = text.lower()

        # Must have an email address to qualify
        emails = self._extract_emails(text)
        if not emails:
            return None

        # Must mention "send resume" / "share CV" / "email" type invite
        invite_pattern = re.compile(
            r"(?:send|share|email|mail|drop|forward|submit)\s+(?:us\s+|me\s+|across\s+)?(?:your\s+)?(?:updated\s+|latest\s+)?(?:resume|cv|profile|application|details)"
            r"|(?:reach\s+out|apply|write)\s+(?:to\s+)?(?:us\s+)?(?:at\s+|via\s+email)"
            r"|(?:interested\s+(?:candidates|people)?\s+can\s+(?:send|share|email|mail))",
            re.IGNORECASE,
        )
        fallback_invites = [
            "send resume", "send your resume", "send cv", "share your cv",
            "mail resume", "email resume", "share resume", "email your cv",
            "send your cv", "drop your resume", "apply via email",
            "send application", "email us your", "mail your resume",
            "forward your resume", "send your application",
        ]
        if not invite_pattern.search(text) and not any(kw in text_lower for kw in fallback_invites):
            return None

        # ── Post Age Filter (Minister's Strict Requirement: <= 3 weeks / 21 days) ──
        time_text = card.get("time_text", "")
        within_3w, age_desc = self._is_within_3_weeks(text, time_text)
        if not within_3w:
            self.logger.info("Skipping post older than 3 weeks (%s): %s", age_desc, text[:80])
            return None

        # ── Location Filter (Strict India-Only Policy Mandate) ──
        if not self._is_location_valid(text_lower):
            self.logger.info("Skipping foreign/non-domestic post: %s", text[:80])
            return None

        # Experience filter: must be fresher-eligible (0-6 months, 6m-1yr, 1-2yr)
        is_fresher = self._is_fresher_eligible(text_lower)
        has_senior = self._has_senior_requirement(text_lower)
        if has_senior and not is_fresher:
            self.logger.debug("Skipping senior-level post: %s", text[:80])
            return None

        # Extract role
        role = self._extract_role(text)

        # Extract subject line with extracted role
        subject_line = self._extract_subject(text, role=role)

        # Extract poster name / company (DOM + heuristic + email domain)
        poster_name = card.get("poster_name_dom") or self._extract_poster_name(text)
        if any(b in poster_name.lower() for b in ["threat", "managed", "assistant", "recruiter", "team", "human resource"]):
            poster_name = "Hiring Team"

        company = self._extract_company(
            text,
            email_addresses=emails,
            headline=card.get("poster_headline_dom", ""),
            post_url=post_url,
        )
        skills_mentioned = self._extract_skills(text_lower)
        experience_hint = self._extract_experience_hint(text_lower)

        return LinkedInPostLead(
            post_url=post_url,
            post_text=text,
            poster_name=poster_name,
            company=company,
            role=role,
            email_addresses=[e for e in emails if e.lower() != self.own_email],
            subject_line=subject_line,
            experience_hint=experience_hint,
            skills_mentioned=skills_mentioned,
            is_fresher_eligible=is_fresher or not has_senior,
            post_age=age_desc,
            raw_snippet=text[:3000],
        )

    # ------------------------------------------------------------------
    # Age & Date verification
    # ------------------------------------------------------------------

    @classmethod
    def _is_within_3_weeks(cls, text: str, time_text: str = "") -> tuple[bool, str]:
        """
        Validates that a post is at most 3 weeks (21 days) old.
        Returns (is_valid, detected_age_str).
        """
        combined = f"{time_text} {text}".lower()

        # Check explicit reject patterns first (e.g. 4w+, 1mo+, 2mo+, 1y+, 22d+)
        for pattern in AGE_REJECT_PATTERNS:
            match = pattern.search(combined)
            if match:
                return False, f"Older than 3 weeks: {match.group(0).strip()}"

        # Check accept patterns (e.g. 1w, 2w, 3w, 1-21d, hours, minutes, today)
        for pattern in AGE_ACCEPT_PATTERNS:
            match = pattern.search(combined)
            if match:
                return True, match.group(0).strip()

        # If no explicit age pattern matched, since the search query is already
        # filtered with datePosted=past-month, check if 'month' or 'year' appears in metadata
        if any(w in time_text.lower() for w in ["month", "yr", "year", "mo"]):
            return False, f"Older than 3 weeks: {time_text}"

        return True, "within 3 weeks (query-filtered)"

    # ------------------------------------------------------------------
    # Helper extractors
    # ------------------------------------------------------------------

    @classmethod
    def _extract_emails(cls, text: str) -> list[str]:
        """Extract valid email addresses from post text, including de-obfuscating anti-bot patterns."""
        normalized_text = cls._deobfuscate_emails(text)
        raw = EMAIL_REGEX.findall(normalized_text)
        seen = set()
        valid = []
        FOREIGN_TLDS = (".ae", ".uk", ".ca", ".au", ".sg", ".ph", ".vn", ".ng", ".pk", ".bd", ".eg", ".de", ".fr", ".co.uk")
        text_lower = text.lower()
        has_domestic = any(re.search(r"\b" + re.escape(dl) + r"\b", text_lower, flags=re.IGNORECASE) for dl in cls.DOMESTIC_LOCATIONS)

        for email in raw:
            # Clean trailing punctuation
            email = email.rstrip(".,;:!?)>]\"'")
            email_lower = email.lower()
            domain = email_lower.split("@", 1)[-1] if "@" in email_lower else ""
            # Skip placeholder/noise domains
            if domain in NOISE_EMAIL_DOMAINS:
                continue
            # Skip strictly foreign TLDs unless domestic Indian context is explicitly stated
            if any(domain.endswith(tld) for tld in FOREIGN_TLDS) and not has_domestic:
                continue
            if email_lower in seen:
                continue
            seen.add(email_lower)
            valid.append(email)
        return valid

    @staticmethod
    def _deobfuscate_emails(text: str) -> str:
        """Decode common obfuscations like 'hr [at] company [dot] com'."""
        s = text
        # replace [at], (at), {at}, [@] with @ (including surrounding spaces)
        s = re.sub(r"\s*[\(\[\{]\s*(?:at|@)\s*[\)\]\}]\s*", "@", s, flags=re.I)
        # replace [dot], (dot), {dot} with . (including surrounding spaces)
        s = re.sub(r"\s*[\(\[\{]\s*dot\s*[\)\]\}]\s*", ".", s, flags=re.I)
        # replace " at " between username and domain
        s = re.sub(r"\b([a-zA-Z0-9._%+-]+)\s+at\s+([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b", r"\1@\2", s, flags=re.I)
        # replace " dot com", " dot in", " dot org", etc.
        s = re.sub(r"\s+dot\s+(com|in|org|net|co|io|ai)\b", r".\1", s, flags=re.I)
        return s

    FOREIGN_LOCATIONS = [
        "united states", "usa", "u.s.", "u.s.a", "uk", "united kingdom", "london",
        "canada", "toronto", "vancouver", "germany", "berlin", "australia", "sydney",
        "melbourne", "dubai", "uae", "singapore", "philippines", "manila", "europe",
        "saudi arabia", "riyadh", "qatar", "doha", "kuwait", "bahrain", "nigeria",
        "lagos", "vietnam", "hanoi", "pakistan", "bangladesh", "sri lanka", "egypt",
    ]
    DOMESTIC_LOCATIONS = [
        "india", "bengaluru", "bangalore", "hyderabad", "pune", "mumbai", "navi mumbai",
        "delhi", "delhi ncr", "new delhi", "noida", "greater noida", "gurgaon", "gurugram",
        "chennai", "kolkata", "ahmedabad", "remote", "work from home", "wfh", "pan india",
        "anywhere in india", "across india", "chandigarh", "mohali", "jaipur", "indore",
        "kochi", "coimbatore",
    ]

    @classmethod
    def _is_location_valid(cls, text: str) -> bool:
        text_lower = text.lower()
        has_foreign = any(re.search(r"\b" + re.escape(fl) + r"\b", text_lower, flags=re.IGNORECASE) for fl in cls.FOREIGN_LOCATIONS)
        has_domestic = any(re.search(r"\b" + re.escape(dl) + r"\b", text_lower, flags=re.IGNORECASE) for dl in cls.DOMESTIC_LOCATIONS)
        # If explicitly foreign and does not mention India or domestic locations, skip
        if has_foreign and not has_domestic:
            return False
        return True

    @staticmethod
    def _is_fresher_eligible(text_lower: str) -> bool:
        return any(kw in text_lower for kw in FRESHER_KEYWORDS)

    @staticmethod
    def _has_senior_requirement(text_lower: str) -> bool:
        return any(kw in text_lower for kw in SENIOR_KEYWORDS)

    @classmethod
    def _extract_role(cls, text: str) -> str:
        text_lower = text.lower()

        # 1. Check explicit role markers in text
        role_marker_patterns = [
            re.compile(r"(?:role|position|designation|job title|profile)[:\s]+([A-Za-z0-9\s/&()-]{4,35}?)(?:\.|\n|,|$)", re.IGNORECASE),
            re.compile(r"(?:hiring|looking for|urgently hiring|openings? for)\s+(?:an?|freshers?|junior)?\s*([A-Za-z0-9\s/&()-]{4,35}?)(?:\.|\n|,|with|for|$)", re.IGNORECASE),
        ]
        for rmp in role_marker_patterns:
            m = rmp.search(text)
            if m:
                candidate = m.group(1).strip().strip("'\"’“”.,;:!- ")
                candidate_lower = candidate.lower()
                if any(k in candidate_lower for k in ["vapt", "penetration", "soc", "security", "appsec", "ethical", "network", "cyber", "python"]):
                    if 4 <= len(candidate) <= 35 and not any(bad in candidate_lower for bad in ["immediate", "joiner", "experience", "candidate", "resume", "fresher", "looking"]):
                        return candidate.title()

        # 2. Check canonical CYBERSEC_ROLES (longest first)
        for role in sorted(CYBERSEC_ROLES, key=len, reverse=True):
            if role.lower() in text_lower:
                return role

        # 3. Contextual fallback based on keywords
        if "penetration" in text_lower or "pentest" in text_lower or "burp" in text_lower:
            return "Penetration Tester"
        if "vapt" in text_lower:
            return "VAPT Analyst"
        if "soc" in text_lower or "siem" in text_lower or "splunk" in text_lower:
            return "SOC Analyst (L1)"
        if "appsec" in text_lower or "owasp" in text_lower or "application security" in text_lower:
            return "Application Security Engineer"
        if "network security" in text_lower:
            return "Network Security Analyst"
        if "ethical hack" in text_lower:
            return "Ethical Hacker"
        if "python" in text_lower:
            return "Python Developer / Security Automation"

        return "Cybersecurity Analyst"

    @classmethod
    def _extract_subject(cls, text: str, role: str = "") -> str:
        for pattern in SUBJECT_PATTERNS:
            match = pattern.search(text)
            if match:
                subject = match.group(1).strip().strip('"\'')
                # Check for false positives: legal disclaimers like "subject to verification", "subject to eligibility", etc.
                if re.match(r"^to\s+", subject, re.IGNORECASE):
                    continue
                if any(disclaimer in subject.lower() for disclaimer in ["eligibility", "verification", "agreed terms", "authorization", "change without", "applicable"]):
                    continue
                if "@" in subject:
                    continue

                # Cut off trailing phrases like ". Thanks", ". Note", punctuation
                subject = re.split(r"\.(?:\s+|$|\n)", subject)[0].strip()
                subject = re.split(r"(?:thanks|thank you|regards|please note|deadline)\b", subject, flags=re.I)[0].strip()
                subject = subject.rstrip(".,;:!- ")
                # Replace placeholder tags in detected subject with candidate profile info
                _cand_name = ''
                _cand_exp = '1 Year Exp'
                _cand_loc = ''
                try:
                    from app.config import load_config
                    from app.profile_loader import load_profile
                    _p = load_profile(load_config().profile_path)
                    _cand_name = _p.name or ''
                    if hasattr(_p, 'experience_years') and _p.experience_years:
                        _cand_exp = f'{_p.experience_years:g} Year(s) Exp'
                    _cand_loc = _p.location or ''
                except Exception:
                    pass

                _name_replace = _cand_name or 'Applicant'
                subject = re.sub(r'\[(?:your\s+)?name\]|<(?:your\s+)?name>|\((?:your\s+)?name\)', _name_replace, subject, flags=re.I)
                subject = re.sub(r'\[(?:candidate\s+)?name\]|<(?:candidate\s+)?name>', _name_replace, subject, flags=re.I)
                subject = re.sub(r'\[(?:exp|experience)\]|<(?:exp|experience)>', _cand_exp, subject, flags=re.I)
                subject = re.sub(r'\[(?:location|city)\]|<(?:location|city)>', _cand_loc or 'Available', subject, flags=re.I)

                if 5 < len(subject) < 150:
                    return subject

        display_role = role or 'Software Engineer'
        _cand_name_str = f' - {_cand_name}' if _cand_name else ''
        return f'Application for {display_role}{_cand_name_str} | {_cand_exp} | Immediate Joiner'
    @staticmethod
    def _extract_poster_name(text: str) -> str:
        # Heuristic: look for "I'm [Name]" or "[Name] here" patterns
        patterns = [
            re.compile(r"(?:Hi|Hello),?\s+I(?:'?m| am)\s+([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})", re.MULTILINE),
            re.compile(r"^([A-Z][a-z]+(?: [A-Z][a-z]+){1,2})\s*(?:here|from|at)\b", re.MULTILINE),
        ]
        bad_tokens = {"threat", "security", "managed", "assistant", "manager", "recruiter", "team", "engineer", "lead", "analyst", "services", "solutions", "cyber", "hiring", "human"}
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                candidate = match.group(1).strip()
                if not any(b in candidate.lower() for b in bad_tokens):
                    return candidate
        return "Hiring Team"

    @classmethod
    def _clean_company_name(cls, raw: str) -> str:
        if not raw:
            return ""
        clean = raw.strip().strip("'\"’“”.,;:!- ")
        clean_lower = clean.lower()
        if clean_lower in EXACT_COMPANY_BLOCKLIST or len(clean) <= 2:
            return ""
        if any(phrase in clean_lower for phrase in GARBAGE_COMPANY_PHRASES):
            return ""
        return clean

    @classmethod
    def _extract_company_from_slug(cls, url: str) -> str:
        if not url:
            return ""
        match = re.search(r"linkedin\.com/company/([a-zA-Z0-9\-_]+)", url)
        if match:
            slug = match.group(1).lower()
            if slug in {"cyber-security-engineer", "reshare-jobs", "reshare-jobs-pakistan", "jobs", "hiring", "careers"}:
                return ""
            words = slug.split("-")
            clean_words = []
            for w in words:
                if w in {"pvt", "ltd", "llp", "inc", "corp"}:
                    clean_words.append(w.capitalize())
                elif len(w) <= 4 and w in {"soc", "vapt", "it", "hr", "ai"}:
                    clean_words.append(w.upper())
                else:
                    clean_words.append(w.capitalize())
            candidate = " ".join(clean_words)
            return cls._clean_company_name(candidate)
        return ""

    @classmethod
    def _extract_company_from_email_domain(cls, email: str) -> str:
        if not email or "@" not in email:
            return ""
        domain = email.split("@", 1)[-1].strip().lower()
        if domain in WEBMAIL_DOMAINS:
            return ""
        base = domain.split(".")[0]
        if base in {"gmail", "yahoo", "outlook", "hotmail", "icloud", "proton", "protonmail"}:
            return ""
        domain_mapping = {
            "ndmsk": "NDMSK",
            "arminnovations": "ARM Innovation",
            "arminnovation": "ARM Innovation",
            "indiancybersecuritysolutions": "Indian Cyber Security Solutions",
            "techtheoryindia": "Tech Theory India",
            "penhexxsecurity": "Penhexx Security",
            "igageinfosystems": "Igage Infosystems",
            "codevirussec": "Codevirus Security",
            "primetekgs": "Primetek GS",
            "fortinex": "Fortinex",
            "sgxmeta": "SGX Meta",
            "stellarmind": "Stellarmind",
            "innometrixtechub": "Innometrix Techub",
            "avepoint": "AvePoint",
            "incrito": "Incrito",
            "jasani": "Jasani",
            "convico": "Convico",
            "careerxperts": "Careerxperts Consulting",
            "talentarchrsolutions": "TalentArch Solutions",
            "redvann": "Redvann",
            "nexviax": "Nexviax",
            "polluxa": "Polluxa",
            "kotechagroup": "Kotecha Group",
            "seaandbeyond": "Sea and Beyond",
            "mitigata": "Mitigata",
            "yatiresource": "Yati Resource",
            "osidigital": "OSI Digital",
            "emagicsolutions": "Emagic Solutions",
        }
        if base in domain_mapping:
            return domain_mapping[base]
        if base.startswith("dgtech"):
            return "DG Tech Asia" if "asia" in domain else "DG Tech"

        words = re.split(r"[-_]", base)
        clean_words = [w.capitalize() for w in words if w]
        candidate = " ".join(clean_words)
        return cls._clean_company_name(candidate)

    @classmethod
    def _extract_company(
        cls,
        text: str,
        email_addresses: list[str] | None = None,
        headline: str = "",
        post_url: str = "",
    ) -> str:
        # 1. URL slug (Highest priority when browsing company page)
        if post_url:
            slug_comp = cls._extract_company_from_slug(post_url)
            if slug_comp:
                return slug_comp

        # 2. Recruiter's corporate business domain (Highest confidence)
        if email_addresses:
            for email in email_addresses:
                domain_comp = cls._extract_company_from_email_domain(email)
                if domain_comp:
                    return domain_comp

        # 3. Recruiter's headline if available (e.g. "HR at ABC Corp")
        if headline:
            m = re.search(r"(?:at|@)\s+([A-Z][a-zA-Z0-9&.\- ]{2,35}?)(?:$|[|\-•,])", headline)
            if m:
                candidate = cls._clean_company_name(m.group(1))
                if candidate:
                    return candidate

        # 4. Explicit corporate suffix in post text
        corp_pattern = re.compile(
            r"([A-Z][a-zA-Z0-9&.\- ]{2,35}?)\s+(?:Pvt\.?\s*Ltd\.?|Private Limited|LLP|Inc\.?|Corp\.?|Corporation|Technologies|Tech Solutions|Infosec)",
            re.MULTILINE
        )
        m_corp = corp_pattern.search(text)
        if m_corp:
            candidate = cls._clean_company_name(m_corp.group(0))
            if candidate:
                return candidate

        # 5. Explicit hiring phrases: "hiring for [Company]", "we at [Company]", "join our team at [Company]"
        hiring_patterns = [
            re.compile(r"(?:hiring for|we at|join our team at|join us at)\s+([A-Z][a-zA-Z0-9&.\- ]{2,35}?)(?:\.|,|\n|\!|\?|;|$)", re.IGNORECASE),
        ]
        for hp in hiring_patterns:
            m = hp.search(text)
            if m:
                candidate = cls._clean_company_name(m.group(1))
                if candidate:
                    return candidate

        return ""

    @staticmethod
    def _extract_skills(text_lower: str) -> list[str]:
        all_skills = [
            "vapt", "owasp", "burp suite", "nmap", "kali linux", "siem", "soc",
            "splunk", "incident response", "vulnerability assessment", "network security",
            "python", "grc", "iso 27001", "penetration testing", "api security",
            "wireshark", "zap", "bug bounty", "cloud security", "azure", "aws",
        ]
        return [s for s in all_skills if s in text_lower]

    @staticmethod
    def _extract_experience_hint(text_lower: str) -> str:
        for kw in ["0-1 year", "0 to 1", "fresher", "0-2 year", "0 to 2", "1-2 year", "1 to 2"]:
            if kw in text_lower:
                return kw
        return "fresher/entry level"

