"""
src/agent.py — Core Autonomous Job Agent Engine.

Coordinates browser automation via Selenium, AI scoring, deduplication via
JavaBridge, and logs all progress cleanly to SQLite and the /logs folder.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from config.settings import settings
from src.browser import get_browser
from src.java_runner import java_runner
from src.tracker import JobRecord, tracker

logger = logging.getLogger("src.agent")


class JobAgent:
    """The central orchestrator for job discovery, scoring, and application automation."""

    def __init__(self) -> None:
        self.settings = settings
        self.tracker = tracker
        self.java_runner = java_runner
        self._configure_logging()

    def _configure_logging(self) -> None:
        """Sets up isolated log routing to /logs/job_agent.log and stdout."""
        log_file = self.settings.log_file_path
        log_file.parent.mkdir(parents=True, exist_ok=True)

        logging.basicConfig(
            level=getattr(logging, self.settings.log_level, logging.INFO),
            format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            handlers=[
                logging.FileHandler(log_file, encoding="utf-8"),
                logging.StreamHandler(),
            ],
        )

    def extract_job_details(self, driver) -> Dict[str, str]:
        """Extracts title, company, location, and description from the active web page."""
        details = {
            "title": "",
            "company": "",
            "location": "",
            "description": "",
        }

        # Common heading selectors across job boards
        title_selectors = [
            "h1",
            ".job-title",
            "[data-job-title]",
            ".topcard__title",
            ".artdeco-entity-lockup__title",
        ]
        for sel in title_selectors:
            elements = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in elements:
                text = el.text.strip()
                if text and len(text) < 120:
                    details["title"] = text
                    break
            if details["title"]:
                break

        # Company selectors
        company_selectors = [
            ".company-name",
            "[data-company-name]",
            ".topcard__flavor--black-link",
            ".artdeco-entity-lockup__subtitle",
            "a[href*='/company/']",
        ]
        for sel in company_selectors:
            elements = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in elements:
                text = el.text.strip()
                if text and len(text) < 100:
                    details["company"] = text
                    break
            if details["company"]:
                break

        # Location selectors
        location_selectors = [
            ".job-location",
            ".topcard__flavor--bullet",
            ".location",
        ]
        for sel in location_selectors:
            elements = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in elements:
                text = el.text.strip()
                if text and len(text) < 80:
                    details["location"] = text
                    break
            if details["location"]:
                break

        # Full body description
        try:
            body = driver.find_element(By.TAG_NAME, "body").text
            details["description"] = body
        except Exception:
            details["description"] = ""

        # Fallbacks
        if not details["title"]:
            details["title"] = driver.title.split("-")[0].strip() or self.settings.target_role
        if not details["company"]:
            details["company"] = "Company"
        if not details["location"]:
            details["location"] = "Remote / Listed"

        return details

    def evaluate_role_match(self, title: str, description: str) -> int:
        """
        Scores job description alignment against user target role and skills.
        Uses JavaBridge for high performance sub-process execution.
        """
        target_skills = [self.settings.target_role] + [loc for loc in self.settings.target_locations]
        skills_arg = ",".join(target_skills)

        # Call JavaBridge scoring
        res = self.java_runner.run_bridge("score", [skills_arg, description[:10000]])
        score = res.get("score", 0)

        # Boost score if target role appears directly in title
        if self.settings.target_role.lower() in title.lower():
            score = min(100, score + 40)

        return score

    def process_url(self, driver, url: str) -> JobRecord:
        """Navigates to a single job URL, scores it, and persists tracking."""
        parsed = urlparse(url)
        source = parsed.netloc.replace("www.", "")

        logger.info("Inspecting job listing: %s", url)
        try:
            driver.get(url)
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            time.sleep(2.0)  # Gentle anti-detection delay
        except Exception as exc:
            logger.warning("Navigation failed or timed out for %s: %s", url, exc)
            rec = JobRecord(
                source=source,
                company="Unknown",
                title="Failed to Load",
                url=url,
                status="failed",
                reason=str(exc),
            )
            self.tracker.record_job(rec)
            return rec

        details = self.extract_job_details(driver)

        # Compute canonical deduplication hash via Java
        hash_res = self.java_runner.run_bridge(
            "hash", [details["company"], details["title"], details["location"]]
        )
        canonical_key = hash_res.get("canonical_key", "")

        # Check if already processed
        if self.tracker.is_already_processed(canonical_key, url):
            logger.info("Skipping already processed job: %s | %s", details["company"], details["title"])
            return JobRecord(
                source=source,
                company=details["company"],
                title=details["title"],
                url=url,
                canonical_key=canonical_key,
                location=details["location"],
                status="skipped",
                reason="Already in database",
            )

        # Score alignment
        score = self.evaluate_role_match(details["title"], details["description"])
        status = "scored" if score >= 50 else "skipped"
        reason = f"Calculated match score: {score}%"

        job = JobRecord(
            source=source,
            company=details["company"],
            title=details["title"],
            url=url,
            canonical_key=canonical_key,
            location=details["location"],
            score=score,
            status=status,
            reason=reason,
        )

        self.tracker.record_job(job)
        logger.info("Recorded job: [%s] %s @ %s | Score: %d%%", status.upper(), job.title, job.company, score)
        return job

    def run_queue(self, urls: List[str]) -> List[JobRecord]:
        """Executes automated processing over an input list of job URLs."""
        results = []
        logger.info("Starting automation queue on %d candidate URLs...", len(urls))

        with get_browser() as driver:
            for idx, url in enumerate(urls, 1):
                clean_url = url.strip()
                if not clean_url or clean_url.startswith("#"):
                    continue
                logger.info("[%d/%d] Processing target: %s", idx, len(urls), clean_url)
                rec = self.process_url(driver, clean_url)
                results.append(rec)

        stats = self.tracker.get_summary_stats()
        logger.info("Queue completed. Current SQLite Summary: %s", stats)
        return results
