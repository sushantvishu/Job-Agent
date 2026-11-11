from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from playwright.sync_api import Page
from app.utils import JobPosting


@dataclass
class JobCandidate:
    """Represents a discovered candidate job before full inspection."""
    url: str
    source: str
    company: str = ""
    title: str = ""
    location: str = ""
    raw_snippet: str = ""


class BaseJobSource(ABC):
    """Abstract Strategy Adapter for platform-specific job scrapers (Naukri, LinkedIn, ATS)."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Name of the platform (naukri, linkedin, company)."""
        ...

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Check if this adapter handles the given URL."""
        ...

    @abstractmethod
    def extract_listing_candidates(self, page: Page) -> list[JobCandidate]:
        """Extract job cards/links from a search results or feed page."""
        ...

    @abstractmethod
    def extract_job_detail(self, page: Page, candidate_url: str = "") -> JobPosting:
        """Extract full job description, metadata, and criteria from an open job page."""
        ...

    @abstractmethod
    def expand_details(self, page: Page) -> None:
        """Click read more/expand description buttons if collapsed."""
        ...
