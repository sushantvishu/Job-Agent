"""
Generate comprehensive VAPT-focused job search URLs for Naukri and LinkedIn Jobs.
No LinkedIn posts. All permutations of role terms x locations x experience levels.
"""
from __future__ import annotations
import re
from urllib.parse import quote, quote_plus
from pathlib import Path

# ── Primary VAPT / Cybersecurity role keywords ──────────────────────────────
VAPT_ROLES = [
    # Core VAPT
    "VAPT",
    "VAPT Analyst",
    "VAPT Engineer",
    "Junior VAPT",
    "Junior VAPT Analyst",
    "VAPT fresher",
    "VAPT trainee",
    "VAPT intern",
    "Vulnerability Assessment Penetration Testing",
    "Vulnerability Assessment",
    "Vulnerability Assessment Analyst",
    "Vulnerability Management",
    "Penetration Tester",
    "Penetration Testing",
    "Junior Penetration Tester",
    "Penetration Testing fresher",
    "Ethical Hacker",
    "Junior Ethical Hacker",
    # Web / App Sec
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
    # Network / Infra
    "Network Security Analyst",
    "Network Security Engineer",
    "Network Penetration Tester",
    "Network VAPT",
    "Cyber Security Analyst",
    "Cybersecurity Analyst",
    "Junior Cybersecurity Analyst",
    "Cyber Security fresher",
    "Information Security Analyst",
    "Information Security Engineer",
    "Security Analyst",
    "Junior Security Analyst",
    # SOC / Blue Team
    "SOC Analyst",
    "Junior SOC Analyst",
    "SOC L1 Analyst",
    "Security Operations Analyst",
    "SIEM Analyst",
    "Security Monitoring Analyst",
    "Alert Triage Analyst",
    "Incident Response Analyst",
    "Threat Analyst",
    "Blue Team Analyst",
    # Red Team
    "Red Team Analyst",
    "Offensive Security Analyst",
    # GRC / Compliance
    "GRC Analyst",
    "GRC Consultant",
    "Information Security Consultant",
    "Security Compliance Analyst",
    "Risk Compliance Analyst",
    # Python / Backend (secondary)
    "Python Developer fresher",
    "Junior Python Developer",
    "Python Backend Developer",
]

# ── India locations for Naukri ───────────────────────────────────────────────
# (path_slug, query_l_param)
NAUKRI_LOCATIONS = [
    ("india",      "india"),
    ("bengaluru",  "bengaluru"),
    ("hyderabad",  "hyderabad"),
    ("pune",       "pune"),
    ("delhi",      "delhi"),
    ("mumbai",     "mumbai"),
    ("noida",      "noida"),
    ("chennai",    "chennai"),
    ("kolkata",    "kolkata"),
    ("ahmedabad",  "ahmedabad"),
    ("remote",     "remote"),
]

# ── LinkedIn location strings ────────────────────────────────────────────────
LINKEDIN_LOCATIONS = [
    "India",
    "Bengaluru, Karnataka, India",
    "Hyderabad, Telangana, India",
    "Pune, Maharashtra, India",
    "Delhi, India",
    "Mumbai, Maharashtra, India",
    "Noida, Uttar Pradesh, India",
    "Chennai, Tamil Nadu, India",
]

# ── Experience levels ────────────────────────────────────────────────────────
# Naukri: 0=fresher, 1=1yr, 2=2yr
NAUKRI_EXP_PARAMS = ["0", "1", "0%2C1", "0%2C1%2C2", "2"]
# LinkedIn: 1=Internship, 2=Entry Level, 3=Associate
LINKEDIN_EXP_PARAMS = ["1%2C2", "2", "1%2C2%2C3", "2%2C3"]

# Fresh posting filter
LINKEDIN_FRESH_FILTER = "r604800"   # 7 days
NAUKRI_FRESH_DAYS = "7"


def role_to_slug(role: str) -> str:
    """Convert role name to Naukri URL slug format."""
    slug = role.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug


def build_naukri_urls() -> list[str]:
    urls: set[str] = set()
    for role in VAPT_ROLES:
        slug = role_to_slug(role)
        enc_k = quote_plus(role)  # k= query param (URL-encoded)
        for loc_slug, loc_label in NAUKRI_LOCATIONS:
            for exp in NAUKRI_EXP_PARAMS:
                # Correct Naukri format: /slug-jobs-in-location?k=keyword&l=location&experience=N
                base_url = (
                    f"https://www.naukri.com/{slug}-jobs-in-{loc_slug}"
                    f"?k={enc_k}&l={loc_label}&experience={exp}"
                )
                urls.add(base_url)
                # With fresh filter (posted in last 7 days)
                urls.add(base_url + f"&jobAge={NAUKRI_FRESH_DAYS}")
    return sorted(urls)


def build_linkedin_urls() -> list[str]:
    urls: set[str] = set()
    for role in VAPT_ROLES:
        enc = quote_plus(role)
        for loc in LINKEDIN_LOCATIONS:
            loc_enc = quote_plus(loc)
            for exp in LINKEDIN_EXP_PARAMS:
                # All dates
                url = (
                    f"https://www.linkedin.com/jobs/search/"
                    f"?keywords={enc}&location={loc_enc}&f_E={exp}"
                )
                urls.add(url)
                # Fresh (last 7 days)
                urls.add(url + f"&f_TPR={LINKEDIN_FRESH_FILTER}")
    return sorted(urls)


def main():
    naukri_urls = build_naukri_urls()
    linkedin_urls = build_linkedin_urls()

    # ── All URLs file ───────────────────────────────────────────────────────
    output_path = Path("jobs/vapt_search_urls.txt")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    all_urls = naukri_urls + linkedin_urls
    output_path.write_text("\n".join(all_urls) + "\n", encoding="utf-8")

    print(f"[OK] Naukri URLs   : {len(naukri_urls):,}")
    print(f"[OK] LinkedIn URLs : {len(linkedin_urls):,}")
    print(f"[OK] Total URLs    : {len(all_urls):,}")
    print(f"[OK] Written to    : {output_path}")

    # ── Fresh-only subset (for faster first queue run) ──────────────────────
    fresh_naukri = [u for u in naukri_urls if "jobAge=" in u]
    fresh_linkedin = [u for u in linkedin_urls if "f_TPR=" in u]
    fresh_all = fresh_naukri + fresh_linkedin
    fresh_path = Path("jobs/vapt_fresh_urls.txt")
    fresh_path.write_text("\n".join(fresh_all) + "\n", encoding="utf-8")
    print(f"[OK] Fresh-only    : {len(fresh_all):,} -> {fresh_path}")

    # ── Naukri-only (no LinkedIn, no posts) ────────────────────────────────
    naukri_fresh_path = Path("jobs/vapt_naukri_fresh.txt")
    naukri_fresh_path.write_text("\n".join(fresh_naukri) + "\n", encoding="utf-8")
    print(f"[OK] Naukri fresh  : {len(fresh_naukri):,} -> {naukri_fresh_path}")


if __name__ == "__main__":
    main()

