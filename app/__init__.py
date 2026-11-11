"""
Job Agent Framework — Autonomous ATS Application and Lead Automation Engine.
"""
from __future__ import annotations

from app.browser import BrowserSession
from app.config import AppConfig, load_config
from app.form_filler import FormFiller
from app.job_collector import JobCollector
from app.matcher import JobMatcher
from app.profile_loader import ProfileData, load_profile
from app.runtime import build_runtime
from app.tracker import JobTracker
from app.utils import JobPosting, MatchResult

__all__ = [
    "AppConfig",
    "load_config",
    "build_runtime",
    "BrowserSession",
    "JobTracker",
    "JobMatcher",
    "FormFiller",
    "JobCollector",
    "ProfileData",
    "load_profile",
    "JobPosting",
    "MatchResult",
]
