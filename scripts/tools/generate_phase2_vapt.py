"""
Generate Phase 2 VAPT Search Seeds:
- Focused on VAPT & Cybersecurity permutations
- All India hubs (India, Bengaluru, Pune, Hyderabad, Delhi NCR, Gurgaon, Noida, Mumbai, Chennai, Kolkata, Ahmedabad, Remote)
- Experience permutations (0, 1, 2, 0-1, 0-2, 1-2, 0-3 yrs)
- Ultra-fresh filters: jobAge=1 (24h), jobAge=3 (3 days), jobAge=7 (7 days) for Naukri;
  f_TPR=r86400 (24h), f_TPR=r259200 (3d), f_TPR=r604800 (7d) for LinkedIn.
- Filter out already-checked search pages using JobTracker.search_page_key.
"""
from __future__ import annotations
import re
import sqlite3
from urllib.parse import quote_plus
from pathlib import Path
from app.tracker import JobTracker

VAPT_ROLES = [
    # Core VAPT & Pentest
    "VAPT",
    "VAPT Analyst",
    "VAPT Engineer",
    "Junior VAPT",
    "Junior VAPT Analyst",
    "VAPT fresher",
    "VAPT trainee",
    "Vulnerability Assessment",
    "Vulnerability Assessment Analyst",
    "Vulnerability Assessment Penetration Testing",
    "Vulnerability Management Analyst",
    "Penetration Tester",
    "Penetration Testing",
    "Junior Penetration Tester",
    "Penetration Testing fresher",
    "Penetration Testing trainee",
    "Ethical Hacker",
    "Junior Ethical Hacker",
    # AppSec / Web / API / Mobile Sec
    "Application Security Analyst",
    "Application Security Engineer",
    "AppSec Analyst",
    "AppSec Engineer",
    "Web Application Security",
    "Web Application Security Tester",
    "Web Application Penetration Tester",
    "Web App VAPT",
    "API Security Tester",
    "API Security Analyst",
    "Mobile Application Security",
    "Mobile App Penetration Tester",
    # Network & Cyber Defense
    "Network Security Analyst",
    "Network Security Engineer",
    "Network Penetration Tester",
    "Network VAPT",
    "Cyber Security Analyst",
    "Cybersecurity Analyst",
    "Junior Cybersecurity Analyst",
    "Cyber Security fresher",
    "Cyber Security trainee",
    "Information Security Analyst",
    "Information Security Engineer",
    "Security Analyst",
    "Junior Security Analyst",
    # SOC / Blue Team
    "SOC Analyst",
    "Junior SOC Analyst",
    "SOC L1 Analyst",
    "SOC L1",
    "Security Operations Analyst",
    "SIEM Analyst",
    "Security Monitoring Analyst",
    "Incident Response Analyst",
    "Threat Analyst",
    # Red Team
    "Red Team Analyst",
    "Offensive Security Analyst",
    # GRC & Consulting
    "GRC Analyst",
    "Information Security Consultant",
    "Security Compliance Analyst",
    # Python & Security Automation
    "Python Security Engineer",
    "Python Developer fresher",
    "Junior Python Developer",
    "Python Backend Developer",
]

NAUKRI_LOCATIONS = [
    ("india", "india"),
    ("bengaluru", "bengaluru"),
    ("hyderabad", "hyderabad"),
    ("pune", "pune"),
    ("delhi", "delhi"),
    ("noida", "noida"),
    ("gurgaon", "gurgaon"),
    ("delhi-ncr", "delhi ncr"),
    ("mumbai", "mumbai"),
    ("chennai", "chennai"),
    ("kolkata", "kolkata"),
    ("ahmedabad", "ahmedabad"),
    ("remote", "remote"),
]

LINKEDIN_LOCATIONS = [
    "India",
    "Bengaluru, Karnataka, India",
    "Hyderabad, Telangana, India",
    "Pune, Maharashtra, India",
    "Delhi, India",
    "Noida, Uttar Pradesh, India",
    "Gurgaon, Haryana, India",
    "Mumbai, Maharashtra, India",
    "Chennai, Tamil Nadu, India",
    "Remote",
]

NAUKRI_EXP = ["0", "1", "2", "0%2C1", "0%2C1%2C2", "1%2C2"]
LINKEDIN_EXP = ["1%2C2", "2", "1", "2%2C3", "1%2C2%2C3"]

NAUKRI_AGE_LIST = ["1", "3", "7", None]  # 24h, 3d, 7d, all-time
LINKEDIN_AGE_LIST = ["r86400", "r259200", "r604800", None]


def role_to_slug(role: str) -> str:
    slug = role.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def build_candidates() -> list[str]:
    urls: set[str] = set()

    # 1. Naukri
    for role in VAPT_ROLES:
        slug = role_to_slug(role)
        enc_k = quote_plus(role)
        for loc_slug, loc_label in NAUKRI_LOCATIONS:
            for exp in NAUKRI_EXP:
                base = f"https://www.naukri.com/{slug}-jobs-in-{loc_slug}?k={enc_k}&l={loc_label}&experience={exp}"
                for age in NAUKRI_AGE_LIST:
                    if age:
                        urls.add(f"{base}&jobAge={age}")
                    else:
                        urls.add(base)

    # 2. LinkedIn Jobs
    for role in VAPT_ROLES:
        enc_k = quote_plus(role)
        for loc in LINKEDIN_LOCATIONS:
            loc_enc = quote_plus(loc)
            for exp in LINKEDIN_EXP:
                base = f"https://www.linkedin.com/jobs/search/?keywords={enc_k}&location={loc_enc}&f_E={exp}"
                for age in LINKEDIN_AGE_LIST:
                    if age:
                        urls.add(f"{base}&f_TPR={age}")
                    else:
                        urls.add(base)

    return list(urls)


def main():
    print("Generating candidate search seeds...")
    candidates = build_candidates()
    print(f"Total candidate URLs generated: {len(candidates):,}")

    # Query search_page_log
    con = sqlite3.connect("jobs.db")
    cur = con.cursor()
    checked_keys = set(r[0] for r in cur.execute("SELECT page_key FROM search_page_log WHERE status='checked'"))
    con.close()
    print(f"Existing checked page keys in DB: {len(checked_keys):,}")

    # Filter out already checked
    fresh_urls = []
    seen_keys = set(checked_keys)
    for u in candidates:
        k = JobTracker.search_page_key(u)
        if k not in seen_keys:
            seen_keys.add(k)
            fresh_urls.append(u)

    print(f"Fresh, un-checked search seeds: {len(fresh_urls):,}")

    # Priority sorting: Ultra-fresh 24h & 3d first, interleaving Naukri and LinkedIn
    naukri_fresh = [u for u in fresh_urls if "naukri" in u]
    linkedin_fresh = [u for u in fresh_urls if "linkedin" in u]

    print(f"  Naukri fresh seeds: {len(naukri_fresh):,}")
    print(f"  LinkedIn fresh seeds: {len(linkedin_fresh):,}")

    # Interleave for balanced portal execution
    interleaved = []
    max_len = max(len(naukri_fresh), len(linkedin_fresh))
    for i in range(max_len):
        if i < len(naukri_fresh):
            interleaved.append(naukri_fresh[i])
        if i < len(linkedin_fresh):
            interleaved.append(linkedin_fresh[i])

    out_file = Path("jobs/vapt_phase2_priority.txt")
    out_file.write_text("\n".join(interleaved) + "\n", encoding="utf-8")
    print(f"[SUCCESS] Wrote {len(interleaved):,} prioritized fresh seeds to {out_file}")


if __name__ == "__main__":
    main()
