from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote_plus, urlparse

from app.browser import BrowserSession
from app.profile_loader import load_resume_text
from app.tracker import JobTracker
from app.utils import (
    compact_whitespace,
    extract_skills_from_text,
    load_json,
    normalize_key,
    unique_list,
)

# BASE_SEARCH_KEYWORDS defines the default search terms used when no profile-specific
# keywords are found. Users should customize this list to match their target roles,
# or the agent will auto-generate keywords from their profile.json target_roles and skills.
# 
# To generate search URLs from your profile automatically, run:
#   python app/main.py generate-searches
BASE_SEARCH_KEYWORDS = [
    "soc analyst fresher",
    "security operations center analyst",
    "cyber security analyst fresher",
    "cybersecurity analyst entry level",
    "information security analyst fresher",
    "junior security analyst",
    "security analyst trainee",
    "grc analyst fresher",
    "vapt fresher",
    "vapt analyst fresher",
    "vapt trainee",
    "vapt intern",
    "junior vapt analyst",
    "vulnerability assessment and penetration testing fresher",
    "vulnerability assessment and penetration testing analyst",
    "vulnerability assessment analyst",
    "vulnerability assessment fresher",
    "penetration testing intern",
    "penetration testing fresher",
    "web application vapt",
    "web app testing fresher",
    "web application testing fresher",
    "web app security testing",
    "web application security testing",
    "web application penetration testing",
    "web app penetration testing",
    "website security testing",
    "security testing fresher",
    "application security testing fresher",
    "network vapt analyst",
    "network security testing fresher",
    "application security trainee",
    "api security tester fresher",
    "siem analyst fresher",
    "incident response analyst fresher",
    "threat analyst fresher",
    "python developer fresher",
    "junior python developer",
    "python backend developer",
    "software engineer python",
    "python developer 1 year experience",
    "python developer 2 years experience",
]


def build_search_keywords(profile: Any) -> list[str]:
    keywords: list[str] = []
    profile_text = normalize_key(
        " ".join(
            [
                profile.summary,
                profile.resume_text,
                " ".join(profile.target_roles),
                " ".join(profile.skills),
                " ".join(profile.derived_skills),
            ]
        )
    )

    role_seeds = unique_list(profile.target_roles)
    role_variant_groups: list[list[str]] = []
    for role in role_seeds:
        normalized_role = normalize_key(role)
        if not normalized_role:
            continue
        variants = [normalized_role]
        if not any(marker in normalized_role for marker in ("fresher", "junior", "trainee", "intern", "entry level", "associate")):
            variants.extend(
                [
                    f"{normalized_role} fresher",
                    f"{normalized_role} junior",
                    f"{normalized_role} trainee",
                    f"{normalized_role} associate",
                ]
            )
        role_variant_groups.append(variants)

    # Round-robin across roles so modest keyword count covers many categories
    max_variants = max((len(group) for group in role_variant_groups), default=0)
    for variant_index in range(max_variants):
        for group in role_variant_groups:
            if variant_index < len(group):
                keywords.append(group[variant_index])

    if any(marker in profile_text for marker in ("python", "fastapi", "backend", "software engineer")):
        keywords.extend(
            [
                "python developer",
                "python backend developer",
                "junior python developer",
                "python software engineer",
                "backend developer python",
                "python developer fresher",
                "python developer 1 year experience",
                "python developer 2 years experience",
            ]
        )
    if any(marker in profile_text for marker in ("vapt", "burp", "owasp", "penetration testing")):
        keywords.extend(
            [
                "application security analyst",
                "penetration tester",
                "web application security analyst",
                "web application penetration tester",
            ]
        )
    if any(marker in profile_text for marker in ("soc", "siem", "splunk", "incident monitoring", "alert triage")):
        keywords.extend(
            [
                "soc analyst l1",
                "security monitoring analyst",
                "siem analyst",
                "cyber defense analyst",
            ]
        )
    if any(marker in profile_text for marker in ("grc", "compliance", "iso 27001")):
        keywords.extend(
            [
                "information security consultant",
                "risk compliance analyst",
                "grc consultant",
            ]
        )
    if "api security" in profile_text:
        keywords.extend(
            [
                "application security tester",
                "api security analyst",
            ]
        )

    keywords.extend(BASE_SEARCH_KEYWORDS)
    return unique_list(keywords)


def prioritize_unsearched_keywords(keywords: list[str], tracker: JobTracker) -> list[str]:
    seen = tracker.get_seen_search_keys()
    unseen: list[str] = []
    already_seen: list[str] = []
    for kw in keywords:
        norm = normalize_key(kw)
        words = [w for w in norm.split() if w not in {"hiring", "india", "job", "jobs", "opening", "openings"}]
        key = " ".join(words) or norm
        if any(key in s or s in key for s in seen):
            already_seen.append(kw)
        else:
            unseen.append(kw)
    return unique_list(unseen + already_seen)


def build_search_urls(
    keywords: list[str],
    include_posts: bool = True,
    include_jobs: bool = True,
    include_naukri_jobs: bool = True,
    include_linkedin_jobs: bool = True,
    fresh_only: bool = False,
    fresh_days: int = 15,
) -> list[str]:
    urls: list[str] = []
    linkedin_fresh_seconds = max(1, fresh_days) * 24 * 60 * 60
    
    naukri_exps = ["0", "0%2C1", "1", "2", "3", "0%2C1%2C2%2C3"]
    linkedin_exps = ["1", "2", "3", "1%2C2", "2%2C3", "1%2C2%2C3"]
    
    for i, keyword in enumerate(keywords):
        encoded = quote_plus(keyword)
        
        n_exp = naukri_exps[i % len(naukri_exps)]
        l_exp = linkedin_exps[i % len(linkedin_exps)]
        
        if include_jobs and include_naukri_jobs:
            naukri_url = f"https://www.naukri.com/jobs-in-india?k={encoded}&l=india&experience={n_exp}"
            if fresh_only:
                naukri_url += f"&jobAge={max(1, fresh_days)}"
            urls.append(naukri_url)
        if include_jobs and include_linkedin_jobs:
            linkedin_url = f"https://www.linkedin.com/jobs/search/?keywords={encoded}&location=India&f_E={l_exp}"
            if fresh_only:
                linkedin_url += f"&f_TPR=r{linkedin_fresh_seconds}"
            urls.append(linkedin_url)
        if include_posts:
            urls.append(
                "https://www.linkedin.com/search/results/content/"
                f"?keywords={encoded}+hiring+India&sortBy=%22date_posted%22"
            )
    return unique_list(urls)


def search_key_from_url(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    raw = ""
    for key in ("keywords", "k", "q"):
        if query.get(key):
            raw = query[key][0]
            break
    if not raw:
        raw = parsed.path
    cleaned = normalize_key(unquote_plus(raw))
    filler_terms = {"hiring", "india", "job", "jobs", "opening", "openings"}
    words = [word for word in cleaned.split() if word not in filler_terms]
    return compact_whitespace(" ".join(words)) or cleaned or "default"


def suggest_profile_headline(profile: Any) -> str:
    if getattr(profile, "headline", "").strip():
        return compact_whitespace(profile.headline)
    role = profile.target_roles[0] if profile.target_roles else "Cybersecurity Analyst"
    skill_pool = unique_list(profile.skills + profile.derived_skills)
    highlight_keys = {"vapt", "api security", "soc", "siem", "burp suite", "splunk", "owasp", "python"}
    highlight_skills = [skill for skill in skill_pool if normalize_key(skill) in highlight_keys]
    if not highlight_skills:
        highlight_skills = skill_pool[:4]
    headline_parts = [role]
    headline_parts.extend(highlight_skills[:5])
    return " | ".join(headline_parts)


def write_profile_audit(profile: Any, profile_path: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "profile_audit_latest.md"
    raw_profile = load_json(profile_path, default={}) or {}
    resume_text = load_resume_text(profile_path)
    resume_skills = extract_skills_from_text(resume_text)
    raw_skill_keys = {normalize_key(skill) for skill in raw_profile.get("skills", [])}
    missing_profile_skills = [skill for skill in resume_skills if normalize_key(skill) not in raw_skill_keys]
    recommended_keywords = build_search_keywords(profile)[:15]
    suggested_headline = suggest_profile_headline(profile)

    lines = [
        "# Profile Audit",
        "",
        "## Recommendation Summary",
        "",
        f"- Suggested headline: {suggested_headline}",
        f"- Target roles in profile: {', '.join(profile.target_roles) or '-'}",
        f"- Preferred locations: {', '.join(profile.preferred_locations) or profile.location or '-'}",
        "",
        "## Resume Signals Missing From profile.json",
        "",
        f"- Resume-derived skills not explicitly listed in profile.json: {', '.join(missing_profile_skills) or 'None detected'}",
        f"- Resume text detected: {'Yes' if resume_text else 'No'}",
        "",
        "## Recommended Searches",
        "",
    ]
    for index, keyword in enumerate(recommended_keywords, start=1):
        lines.append(f"{index}. {keyword}")

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- If LinkedIn or Naukri recommendations are off-target, update the visible headline, skills, Open To roles, and location preferences using the exact keywords above.",
            "- Your resume shows a cyber transition from prior support roles, so searches should include junior, trainee, associate, and entry-level variants instead of only fresher terms.",
        ]
    )
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def write_search_alert_inputs(keywords: list[str], jobs_dir: Path) -> tuple[Path, Path]:
    jobs_dir.mkdir(parents=True, exist_ok=True)
    queries_path = jobs_dir / "search_alert_queries.txt"
    urls_path = jobs_dir / "search_alert_urls.txt"
    urls = build_search_urls(keywords, include_posts=False, include_jobs=True)
    queries_path.write_text("\n".join(keywords) + "\n", encoding="utf-8")
    urls_path.write_text("\n".join(urls) + "\n", encoding="utf-8")
    return queries_path, urls_path


def naukri_search_url(keyword: str) -> str:
    return f"https://www.naukri.com/jobs-in-india?k={quote_plus(keyword)}&l=india&experience=0%2C1"


def linkedin_search_url(keyword: str) -> str:
    return f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(keyword)}&location=India&f_E=1%2C2%2C3"


def alert_name_for_keyword(keyword: str) -> str:
    cleaned = compact_whitespace(keyword)
    return cleaned.title()[:80]


def create_naukri_alert(page: Any, keyword: str) -> str:
    trigger = page.locator("text=/Send me jobs like these/i").first
    if not trigger.count():
        return "naukri alert control not found"

    try:
        trigger.click(timeout=5000)
        page.wait_for_timeout(1200)
        alert_name = page.locator("input[name='AlertName']").first
        if not alert_name.count():
            return "naukri alert form not found"
        alert_name.fill(alert_name_for_keyword(keyword))
        page.get_by_role("button", name="Save").first.click(timeout=5000)
        page.wait_for_timeout(1800)
        body = compact_whitespace(page.locator("body").inner_text(timeout=5000)).lower()
        if "alert name is required" in body:
            return "naukri alert save failed: missing alert name"
        if page.locator("input[name='AlertName']").count() == 0:
            return "created"
        if "already" in body and "alert" in body:
            return "already exists"
        return "naukri alert save needs review"
    except Exception as exc:  # noqa: BLE001
        return f"naukri alert failed: {exc}"


def create_linkedin_alert(page: Any) -> str:
    toggle = page.locator("label[data-artdeco-toggle-label='true']").first
    switch = page.get_by_role("switch").first
    if not toggle.count() or not switch.count():
        return "linkedin alert control not found"

    try:
        if switch.get_attribute("aria-checked") == "true":
            return "already on"
        page.evaluate(
            """
            () => {
                const label = document.querySelector("label[data-artdeco-toggle-label='true']");
                if (label) {
                    label.click();
                }
            }
            """
        )
        page.wait_for_timeout(1200)
        body = compact_whitespace(page.locator("body").inner_text(timeout=5000)).lower()
        if "job alert could not be created" in body and "email" in body:
            return "blocked: confirm linkedin email"
        if switch.get_attribute("aria-checked") == "true":
            return "created"
        if "job alert created" in body:
            return "created"
        return "linkedin alert not enabled"
    except Exception as exc:  # noqa: BLE001
        return f"linkedin alert failed: {exc}"


def write_search_alert_report(rows: list[dict], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "search_alerts_latest.md"
    lines = ["# Search Alerts", ""]
    if not rows:
        lines.append("No alert attempts were recorded.")
    for index, row in enumerate(rows, start=1):
        lines.extend(
            [
                f"## {index}. {row.get('keyword') or '-'}",
                "",
                f"- Source: {row.get('source') or '-'}",
                f"- Status: {row.get('status') or '-'}",
                f"- URL: {row.get('url') or '-'}",
                "",
            ]
        )
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def open_alert_page(browser: BrowserSession, url: str, attempts: int = 2) -> tuple[Any, str]:
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            return browser.goto(url), ""
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    return None, str(last_error or "unknown navigation error")
