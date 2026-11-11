from __future__ import annotations

import difflib
import json
import logging
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"

# TARGET_ROLE_KEYWORDS is the set of job title patterns the agent scores positively.
# Customize this to match your target domain. The agent also reads target_roles
# from profile/profile.json at runtime; this set provides fallback matching.
TARGET_ROLE_KEYWORDS = {
    "python developer",
    "python backend developer",
    "python engineer",
    "python backend engineer",
    "backend developer",
    "backend engineer",
    "software engineer",
    "software developer",
    "junior python developer",
    "python programmer",
    "python automation engineer",
    "python",
    "vapt analyst",
    "web application security tester",
    "cybersecurity analyst",
    "soc analyst",
    "grc analyst",
    "information security analyst",
    "api security tester",
    "application security testing",
    "vulnerability assessment analyst",
    "security operations fresher",
    "junior security analyst",
    "application security",
    "security analyst",
    "penetration tester",
    "pentester",
    "security testing",
    "vapt",
    "vulnerability assessment and penetration testing",
    "web app penetration testing",
    "web app security testing",
    "web app testing",
    "web application penetration testing",
    "web application security testing",
    "web application testing",
    "website security testing",
    "ethical hacker",
    "junior ethical hacker",
    "appsec engineer",
    "appsec analyst",
    "penetration testing",
    "junior penetration tester",
    "pen tester",
    "vapt engineer",
    "vapt consultant",
    "vapt tester",
    "network vapt",
    "network security analyst",
    "network security engineer",
    "security engineer",
    "vulnerability assessment",
    "vulnerability management",
    "vulnerability analyst",
    "red team",
    "blue team",
    "threat analyst",
    "siem analyst",
}

SECURITY_SKILLS = {
    "alert triage",
    "api security",
    "asyncio",
    "aws",
    "aws ec2",
    "azure",
    "bash",
    "bug bounty",
    "burp suite",
    "ccna",
    "cloud security",
    "compliance",
    "cve",
    "cybersecurity",
    "docker",
    "edr",
    "fastapi",
    "git",
    "grc",
    "incident response",
    "iso 27001",
    "kali linux",
    "mitre att&ck",
    "nmap",
    "owasp top 10",
    "owasp",
    "penetration testing",
    "python",
    "recon",
    "redis",
    "rest api",
    "rest apis",
    "security operations center",
    "security testing",
    "servicenow",
    "siem",
    "soc",
    "splunk",
    "sql",
    "threat hunting",
    "vapt",
    "vulnerability assessment",
    "web app penetration testing",
    "web app security testing",
    "web app testing",
    "web application penetration testing",
    "web application security testing",
    "web application testing",
    "web security",
    "websockets",
    "website security testing",
    "wireshark",
    "wazuh",
    "zap",
}

DISALLOWED_JOB_KEYWORDS = {
    "bpo",
    "call center",
    "customer support",
    "inside sales",
    "manager",
    "sales",
    "senior manager",
    "senior analyst",
    "support executive",
    "telecaller",
    "telecalling",
}

SENSITIVE_DATA_KEYWORDS = {
    "aadhaar",
    "bank account",
    "credit card",
    "debit card",
    "ifsc",
    "otp",
    "pan card",
    "passport number",
    "routing number",
    "social security",
    "ssn",
    "verification code",
}

CAPTCHA_KEYWORDS = {
    "captcha",
    "email verification",
    "otp",
    "phone verification",
    "security check",
    "verification code",
}


class AddressData(BaseModel):
    city: str = "Bengaluru"
    state: str = "Karnataka"
    postal_code: str = "560001"
    country: str = "India"
    country_code: str = "India (+91)"


class EducationData(BaseModel):
    highest_degree: str = "Bachelor's Degree (B.Tech in Computer Science / Cybersecurity)"
    field_of_study: str = "Computer Science / Cybersecurity"
    institution: str = ""
    graduation_year: str = "2024"
    gpa: str = ""


class WorkEligibilityData(BaseModel):
    work_authorization: str = "Yes"
    visa_sponsorship: str = "No"
    willing_to_relocate: str = "Yes"
    willing_to_work_shifts: str = "Yes"
    gender: str = "Male"
    marital_status: str = "Single"


class CompensationData(BaseModel):
    current_salary: str = "0 LPA (Fresher)"
    expected_salary: str = "₹4.5 LPA (4-6 LPA)"
    currency: str = "INR"


class ProfileData(BaseModel):
    name: str
    email: str
    phone: str
    headline: str = ""
    location: str
    preferred_locations: list[str] = Field(default_factory=list)
    notice_period: str = "Immediate"
    expected_salary: str = "As per company standards"
    summary: str = ""
    experience_years: float = 0.0
    skills: list[str] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=list)
    links: dict[str, str] = Field(default_factory=dict)
    custom_answers: dict[str, str] = Field(default_factory=dict)
    resume_text: str = ""
    derived_skills: list[str] = Field(default_factory=list)
    address: AddressData = Field(default_factory=AddressData)
    education: EducationData = Field(default_factory=EducationData)
    work_eligibility: WorkEligibilityData = Field(default_factory=WorkEligibilityData)
    compensation: CompensationData = Field(default_factory=CompensationData)

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if "@" not in v or "." not in v:
            raise ValueError(f"Invalid candidate email address: {v}")
        return v.strip().lower()

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        digits = re.sub(r"\D", "", v)
        if len(digits) < 10:
            raise ValueError(f"Invalid candidate phone (must contain at least 10 digits): {v}")
        return v.strip()


class JobPosting(BaseModel):
    source: str
    company: str = ""
    title: str = ""
    url: str
    application_url: str = ""
    location: str = ""
    experience: str = ""
    skills: list[str] = Field(default_factory=list)
    criteria_text: str = ""
    expansion_audit: str = ""
    description: str = ""
    raw_text: str = ""


class MatchResult(BaseModel):
    score: int
    decision: str
    reasons: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    matched_skills: list[str] = Field(default_factory=list)
    min_years_required: int = 0
    max_years_required: int = 0
    auto_submit_safe: bool = False


class FillResult(BaseModel):
    status: str
    filled_fields: list[str] = Field(default_factory=list)
    skipped_fields: list[str] = Field(default_factory=list)
    guessed_fields: list[str] = Field(default_factory=list)
    unknown_questions: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    submit_blockers: list[str] = Field(default_factory=list)
    ready_to_submit: bool = False
    auto_submitted: bool = False


def setup_logger(log_path: Path, level: str = "INFO") -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("job_agent")
    resolved_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(resolved_level)
    if logger.handlers:
        return logger

    formatter = logging.Formatter(LOG_FORMAT)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(resolved_level)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(resolved_level)
    logger.addHandler(stream_handler)

    logger.propagate = False
    return logger


def load_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def compact_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_key(value: str) -> str:
    cleaned = compact_whitespace(value).lower()
    cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)
    return compact_whitespace(cleaned)


FUZZY_MATCH_THRESHOLD = 0.82


def fuzzy_match_key(query: str, candidate_keys: list[str], threshold: float = FUZZY_MATCH_THRESHOLD) -> str | None:
    """Best-effort match of an already-normalize_key()'d query against normalize_key()'d candidates."""
    if not query or not candidate_keys:
        return None
    best_key: str | None = None
    best_ratio = 0.0
    for candidate in candidate_keys:
        ratio = difflib.SequenceMatcher(None, query, candidate).ratio()
        if ratio > best_ratio:
            best_ratio, best_key = ratio, candidate
    return best_key if best_ratio >= threshold else None


def unique_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        normalized = normalize_key(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(compact_whitespace(value))
    return ordered


def detect_source_from_url(url: str) -> str:
    lowered = url.lower()
    if "linkedin.com" in lowered:
        return "linkedin"
    if "naukri.com" in lowered:
        return "naukri"
    if "instahyre.com" in lowered:
        return "instahyre"
    if "foundit.in" in lowered or "monsterindia.com" in lowered:
        return "foundit"
    if "wellfound.com" in lowered or "angel.co" in lowered:
        return "wellfound"
    return "company"


def extract_years_range(text: str) -> tuple[int, int]:
    lowered = normalize_key(text)
    ranges = re.findall(r"(\d+)\s*(?:to|-)\s*(\d+)\s*years", lowered)
    if ranges:
        start, end = ranges[0]
        return int(start), int(end)

    plus_years = re.findall(r"(\d+)\s*\+?\s*years", lowered)
    if plus_years:
        years = int(plus_years[0])
        return years, years

    fresher_patterns = ("fresher", "entry level", "junior", "trainee", "intern")
    if any(pattern in lowered for pattern in fresher_patterns):
        return 0, 2

    return 0, 0


def extract_skills_from_text(text: str) -> list[str]:
    lowered = normalize_key(text)
    hits = [skill for skill in SECURITY_SKILLS if normalize_key(skill) in lowered]
    return unique_list(hits)


def contains_any_keyword(text: str, keywords: set[str]) -> bool:
    lowered = normalize_key(text)
    return any(normalize_key(keyword) in lowered for keyword in keywords)


def domain_from_url(url: str) -> str:
    stripped = re.sub(r"^https?://", "", url.strip(), flags=re.IGNORECASE)
    return stripped.split("/")[0]


def safe_timestamp() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y%m%d_%H%M%S")


def contains_word(keyword: str, text: str) -> bool:
    return bool(re.search(r"\b" + re.escape(keyword) + r"(?:\b|s\b)", text))
