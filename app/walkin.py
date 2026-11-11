"""
app/walkin.py — Physical Walk-In Interview Classifier & Dispatcher.

Identifies walk-in recruitment drives (which lack online web forms), parses venue
addresses, reporting dates, contact SPOCs, and documents, emits a clean daily digest,
and prevents form fillers from timing out on missing submit buttons.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from app.utils import JobPosting, compact_whitespace, normalize_key

logger = logging.getLogger("walkin")

WALKIN_SIGNALS = [
    re.compile(r"\bwalk[\s-]*in\b", re.IGNORECASE),
    re.compile(r"\bdirect\s+walkin\b", re.IGNORECASE),
    re.compile(r"\bwalkin\s+drive\b", re.IGNORECASE),
    re.compile(r"\bwalk-in\s+interview\b", re.IGNORECASE),
    re.compile(r"\bface[\s-]to[\s-]face\s+interview\b", re.IGNORECASE),
]

VENUE_PATTERNS = [
    re.compile(r"(?:venue|location|address|walk-in\s+location|interview\s+venue)\s*[:\-]\s*([^\n\r]+(?:[\n\r]+[^\n\r]+){1,3})", re.IGNORECASE),
    re.compile(r"(?:venue|address)\s*[:\-]\s*(.*?)(?=(?:contact|date|time|spoc|documents|$))", re.IGNORECASE | re.DOTALL),
]

DATE_PATTERNS = [
    re.compile(r"(?:date|dates|walk-in\s+dates?|interview\s+dates?)\s*[:\-]\s*([^\n\r]+)", re.IGNORECASE),
    re.compile(r"(\b\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s*(?:202\d)?\b)", re.IGNORECASE),
]

TIME_PATTERNS = [
    re.compile(r"(?:time|timing|timings)\s*[:\-]\s*([^\n\r]+)", re.IGNORECASE),
    re.compile(r"(\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\s*(?:to|-)\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)\b)", re.IGNORECASE),
]

CONTACT_PATTERNS = [
    re.compile(r"(?:contact|spoc|hr|recruiter|person)\s*[:\-]\s*([^\n\r]+)", re.IGNORECASE),
]


def is_walkin_requisition(title: str, text: str = "") -> bool:
    """Return True if the title or text indicates a physical walk-in interview."""
    norm_title = (title or "").lower()
    for pattern in WALKIN_SIGNALS:
        if pattern.search(norm_title):
            return True
    # If title doesn't say walk-in, check for prominent venue/reporting in text
    if any(k in text.lower() for k in ("interview venue:", "walk-in venue:", "walk-in date:", "reporting time:")):
        return True
    return False


def extract_walkin_details(job: JobPosting, text: str = "") -> dict[str, str]:
    """Parse venue, date, time, and contact information from a walk-in requisition."""
    content = text or job.raw_text or job.description or ""
    
    venue = "See posting description"
    for vp in VENUE_PATTERNS:
        m = vp.search(content)
        if m:
            clean = compact_whitespace(m.group(1))
            if len(clean) > 8 and not any(clean.lower().startswith(p) for p in ("date", "time", "contact")):
                venue = clean[:250]
                break

    interview_date = "Check posting for exact dates"
    for dp in DATE_PATTERNS:
        m = dp.search(content)
        if m:
            clean = compact_whitespace(m.group(1))
            if len(clean) > 3:
                interview_date = clean[:80]
                break

    interview_time = "Standard business hours (10:00 AM - 4:00 PM)"
    for tp in TIME_PATTERNS:
        m = tp.search(content)
        if m:
            clean = compact_whitespace(m.group(1))
            if len(clean) > 3:
                interview_time = clean[:80]
                break

    contact = "HR Team"
    for cp in CONTACT_PATTERNS:
        m = cp.search(content)
        if m:
            clean = compact_whitespace(m.group(1))
            if len(clean) > 3:
                contact = clean[:100]
                break

    return {
        "title": job.title,
        "company": job.company,
        "url": job.url,
        "location": job.location,
        "interview_date": interview_date,
        "interview_time": interview_time,
        "venue": venue,
        "contact": contact,
    }


def emit_walkin_brief(walkins: list[dict[str, str]], output_path: Path) -> Path:
    """Write an executive walk-in schedule digest for physical recruitment drives."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Upcoming Walk-In Interview Drives Schedule",
        "",
        f"**Generated:** {Path(output_path).stat().st_mtime if output_path.exists() else 'Today'}",
        f"**Total Drives Identified:** {len(walkins)}",
        "",
        "---",
        "",
    ]
    for w in walkins:
        lines.extend([
            f"### {w['title']} @ {w['company']}",
            f"- **Location/City:** {w.get('location', 'India')}",
            f"- **Date(s):** {w['interview_date']}",
            f"- **Timing:** {w['interview_time']}",
            f"- **Venue:** {w['venue']}",
            f"- **Contact / SPOC:** {w['contact']}",
            f"- **Link:** {w['url']}",
            "",
            "---",
            "",
        ])
    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Saved walk-in schedule to %s (%d drives)", output_path, len(walkins))
    return output_path
