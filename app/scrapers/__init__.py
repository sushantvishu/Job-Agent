from __future__ import annotations

from app.scrapers.base import BaseJobSource, JobCandidate
from app.scrapers.naukri import NaukriAdapter
from app.scrapers.linkedin_jobs import LinkedInJobsAdapter
from app.scrapers.company_ats import CompanyATSAdapter
from app.scrapers.instahyre import InstahyreAdapter
from app.scrapers.foundit import FounditAdapter
from app.scrapers.wellfound import WellfoundAdapter

__all__ = [
    "BaseJobSource",
    "JobCandidate",
    "NaukriAdapter",
    "LinkedInJobsAdapter",
    "CompanyATSAdapter",
    "InstahyreAdapter",
    "FounditAdapter",
    "WellfoundAdapter",
]
