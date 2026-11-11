from __future__ import annotations

import re
from typing import Any

from app.matcher import TECHNICAL_SUPPORT_FALLBACK_DECISION
from app.utils import MatchResult, JobPosting, compact_whitespace, unique_list


def is_browser_closed_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "target page, context or browser has been closed" in text
        or "targetclosederror" in text
        or "browser has been closed" in text
        or "context has been closed" in text
        or "page has been closed" in text
    )


def skip_linkedin_non_job_content_url(collector: Any, url: str) -> bool:
    """Return True for LinkedIn article/profile/feed URLs that should never be opened as jobs."""
    lowered = (url or "").lower()
    if "/jobs/search" in lowered or "/jobs/collections" in lowered:
        return False
    if hasattr(collector, "is_non_job_content_url") and collector.is_non_job_content_url(url):
        return True
    return False


def detect_apply_path(page: Any) -> str:
    try:
        body = compact_whitespace(page.locator("body").inner_text(timeout=5000)).lower()
    except Exception:  # noqa: BLE001
        body = ""

    if page.locator("input[type='password']").count():
        return "login required"
    if any(text in body for text in ("already applied", "application submitted", "you applied", "application received")):
        return "already applied"
    if "easy apply" in body:
        return "linkedin easy apply"
    if any(
        text in body
        for text in (
            "apply on company website",
            "apply on company site",
            "company website",
            "responses managed off linkedin",
        )
    ):
        return "company website"
    if find_contact_methods(body):
        return "contact available"
    if "apply now" in body or "apply" in body:
        return "apply button"
    return "review needed"


def find_contact_methods(text: str) -> list[str]:
    contacts: list[str] = []
    for email in re.findall(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b", text or ""):
        lowered = email.lower()
        if lowered.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            continue
        if any(noise in lowered for noise in ("example@", "noreply@", "no-reply@", "privacy@", "support@naukri")):
            continue
        contacts.append(f"email:{email}")

    phone_patterns = [
        r"(?:\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}\b",
        r"\b0[6-9]\d{9}\b",
    ]
    for pattern in phone_patterns:
        for phone in re.findall(pattern, text or ""):
            normalized = re.sub(r"[^\d+]", "", phone)
            digits = re.sub(r"\D", "", normalized)
            if 10 <= len(digits) <= 13:
                contacts.append(f"phone:{normalized}")
    return unique_list(contacts)[:5]


def has_actionable_apply_or_contact(apply_path: str, contacts: list[str]) -> bool:
    lowered = (apply_path or "").lower()
    if contacts:
        return True
    return any(
        marker in lowered
        for marker in (
            "already applied",
            "apply button",
            "company website",
            "contact available",
            "direct apply",
            "easy apply",
            "linkedin easy apply",
        )
    )


def skip_reason_for_match(match: MatchResult, status: str, apply_path: str = "") -> str:
    if status == "shortlisted":
        return ""
    if status == "applied":
        return "already applied"
    parts: list[str] = []
    if match.red_flags:
        parts.append("; ".join(match.red_flags))
    if match.max_years_required >= 5 or match.min_years_required >= 5:
        parts.append("experience too high: 5+ years")
    elif match.max_years_required >= 3 or match.min_years_required >= 3:
        parts.append("experience too high: 3+ years")
    if match.decision == "skip":
        parts.append("score below shortlist threshold")
    if apply_path == "review needed":
        parts.append("apply path needs manual review")
    return compact_whitespace("; ".join(unique_list(parts))) or match.decision


def apply_path_group(value: str) -> str:
    lowered = (value or "").lower()
    if "easy apply" in lowered:
        return "LinkedIn Easy Apply"
    if "company website" in lowered:
        return "Apply On Company Website"
    if "already applied" in lowered:
        return "Already Applied"
    if "review" in lowered or "login" in lowered:
        return "Manual Review"
    if "apply" in lowered:
        return "Direct Apply"
    return "Manual Review"


def review_group_for_row(row: dict) -> str:
    if row.get("decision") == TECHNICAL_SUPPORT_FALLBACK_DECISION:
        return "Technical Support Fallback"
    return apply_path_group(row.get("apply_path", ""))


def duplicate_note_for_job(tracker: Any, job: JobPosting) -> str:
    """Non-blocking check: is this possibly the same posting as one already applied to (same
    company, near-identical title, e.g. a repost or a cross-platform duplicate)? Never used to
    skip/hide a job -- only to surface an informational note, since a wrong match here should
    never cost the user a real opportunity."""
    match = tracker.find_possible_duplicate_applied(job.company, job.title, job.location)
    if not match:
        return ""
    applied_at = match.get("applied_at") or "date not recorded"
    return (
        f"Possibly the same posting as one you already applied to: "
        f"'{match.get('title') or 'Unknown title'}' at {match.get('company') or 'Unknown company'} "
        f"({applied_at}) - {match.get('url') or ''}"
    )
