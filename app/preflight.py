"""
app/preflight.py — Ultra-Fast Pre-Flight Requisition Verifier.

Executes lightweight HTTP HEAD/GET probes in ~50ms before launching heavy Playwright
Google Chrome sessions, immediately pruning expired listings (Naukri expJD=true,
LinkedIn expired_jd_redirect, HTTP 404/410) without wasting browser cycles or RAM.
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import requests

logger = logging.getLogger("preflight")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/133.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class PreFlightChecker:
    """Pre-flight network check executed before launching Playwright browser sessions."""

    _cache: dict[str, tuple[bool, str]] = {}

    @classmethod
    def check_url(cls, url: str, timeout: float = 5.0) -> tuple[bool, str]:
        """Probe the URL to verify it is active.

        Returns (is_active: bool, reason: str).
        """
        if not url:
            return False, "Empty URL"

        if url in cls._cache:
            return cls._cache[url]

        parsed = urlparse(url)
        lowered = url.lower()

        # Reject foreign LinkedIn country subdomains immediately
        netloc = parsed.netloc.lower()
        if netloc.endswith(".linkedin.com") and not (netloc == "www.linkedin.com" or netloc == "in.linkedin.com" or netloc == "linkedin.com"):
            result = (False, f"Foreign LinkedIn subdomain ({netloc}) - Target policy: India/Remote only")
            cls._cache[url] = result
            return result

        try:
            # Use GET with stream=True so we only fetch headers without downloading heavy bodies
            resp = requests.get(
                url,
                headers=DEFAULT_HEADERS,
                allow_redirects=True,
                timeout=timeout,
                stream=True,
            )
            final_url = resp.url.lower()

            # 1. Naukri Expired Job Redirect Detection
            if "expjd=true" in final_url or ("naukri.com" in final_url and "job-listings" not in final_url and "naukri.com/" in final_url):
                result = (False, "Expired Naukri Requisition (Redirected to search/expJD=true)")
                cls._cache[url] = result
                return result

            # 2. LinkedIn Expired Job Redirect Detection
            if "trk=expired_jd_redirect" in final_url or ("linkedin.com/jobs/view" in lowered and "/jobs/search" in final_url):
                result = (False, "Expired LinkedIn Job (Redirected away from job view)")
                cls._cache[url] = result
                return result

            # 3. HTTP Error Statuses
            if resp.status_code in (404, 410):
                result = (False, f"Dead Requisition (HTTP {resp.status_code})")
                cls._cache[url] = result
                return result

            if resp.status_code >= 400 and resp.status_code != 403:
                # 403 might just be anti-bot for requests client while Chrome works fine;
                # but 500, 502, 503, 404 are genuine dead endpoints
                if resp.status_code in (500, 502, 503):
                    result = (False, f"Server Error on Requisition (HTTP {resp.status_code})")
                    cls._cache[url] = result
                    return result

            result = (True, "Active")
            cls._cache[url] = result
            return result

        except requests.RequestException as exc:
            # If network error or timeout during preflight, fail open so browser can attempt
            logger.debug("Pre-flight probe note for %s: %s (falling back to browser)", url, exc)
            return True, "Pre-flight bypassed (network exception)"
