"""
generate_urls.py  — Master URL generator for the job-agent pipeline.

Generates ALL permutations of:
  ROLES × EXPERIENCE_TERMS × NAUKRI_EXP_PARAMS   →  Naukri search URLs
  ROLES × EXPERIENCE_TERMS                        →  LinkedIn search URLs
  ROLES × LOCATIONS                               →  Location-specific Naukri URLs

Run this whenever you want to refresh jobs/urls.txt.
The output file is consumed by `app.main scout` at 2:00 AM.
"""

from __future__ import annotations
import urllib.parse
from pathlib import Path

# ─────────────────────────────────────────────
# 1. JOB ROLES / KEYWORDS
# ─────────────────────────────────────────────
ROLES = [
    # Core security roles
    "VAPT Analyst",
    "SOC Analyst",
    "Cyber Security Analyst",
    "Cybersecurity Analyst",
    "Information Security Analyst",
    "Application Security",
    "Application Security Analyst",
    "API Security",
    "GRC Analyst",
    # Junior / entry level variants
    "Junior Security Analyst",
    "Junior Cybersecurity Analyst",
    "Junior SOC Analyst",
    "Junior VAPT Analyst",
    "Junior Penetration Tester",
    # Freshers / interns
    "Cybersecurity Fresher",
    "Security Analyst Fresher",
    "Cyber Security Intern",
    "Security Intern",
    "Penetration Testing Intern",
    # Broader security keywords
    "Penetration Tester",
    "Pen Tester",
    "Vulnerability Assessment",
    "Bug Bounty",
    "Ethical Hacker",
    "SOC Engineer",
    "Security Operations",
    "Security Engineer",
    "Threat Analyst",
    "Malware Analyst",
]

# ─────────────────────────────────────────────
# 2. EXPERIENCE TERMS (appended to search query text)
# ─────────────────────────────────────────────
EXPERIENCE_TERMS = [
    "",            # bare role name only
    "fresher",
    "entry level",
    "0 years",
    "0-1 year",
    "1 year",
    "1-2 years",
    "intern",
]

# ─────────────────────────────────────────────
# 3. NAUKRI EXPERIENCE PARAMETER VALUES (0/1/2 years)
# ─────────────────────────────────────────────
NAUKRI_EXP_PARAMS = [0, 1, 2]

# ─────────────────────────────────────────────
# 4. PREFERRED LOCATIONS  (appended to Naukri URLs)
# ─────────────────────────────────────────────
NAUKRI_LOCATIONS = [
    "bengaluru",
    "hyderabad",
    "pune",
    "delhi",
    "mumbai",
    "noida",
    "remote",
    "india",   # catch-all / pan-India
]

# ─────────────────────────────────────────────────────────
# 5. LINKEDIN  —  Experience-level filters
#    f_E=1  Internship
#    f_E=2  Entry level
#    f_E=3  Associate      ← include to catch "associate" roles
# ─────────────────────────────────────────────────────────
LINKEDIN_EXP_FILTER = "f_E=1%2C2%2C3"

# LinkedIn only returns useful results per city — add location variants
LINKEDIN_LOCATIONS = [
    "India",
    "Bengaluru, Karnataka, India",
    "Hyderabad, Telangana, India",
    "Pune, Maharashtra, India",
    "Delhi, India",
    "Mumbai, Maharashtra, India",
    "Noida, Uttar Pradesh, India",
]


def slugify(text: str) -> str:
    return text.lower().replace(" ", "-").replace("/", "-").replace("--", "-")


def generate_urls() -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def add(u: str) -> None:
        if u not in seen:
            seen.add(u)
            urls.append(u)

    # ── NAUKRI ──────────────────────────────────────────────────────────
    urls.append("# ================================================================")
    urls.append("# NAUKRI — role × experience_term × exp_param × location")
    urls.append("# ================================================================")

    for role in ROLES:
        for term in EXPERIENCE_TERMS:
            query = f"{role} {term}".strip()
            encoded_k = urllib.parse.quote(query)
            slug = slugify(query)

            for exp in NAUKRI_EXP_PARAMS:
                # Pan-India (no location suffix)
                add(
                    f"https://www.naukri.com/{slug}-jobs-in-india"
                    f"?k={encoded_k}&l=india&experience={exp}"
                )
                # Per preferred city
                for loc in NAUKRI_LOCATIONS:
                    if loc == "india":
                        continue  # already added above
                    add(
                        f"https://www.naukri.com/{slug}-jobs-in-{loc}"
                        f"?k={encoded_k}&l={loc}&experience={exp}"
                    )

    # ── LINKEDIN ────────────────────────────────────────────────────────
    urls.append("")
    urls.append("# ================================================================")
    urls.append("# LINKEDIN — role × experience_term × location")
    urls.append("# Note: LinkedIn jobs are scouted for title/company discovery.")
    urls.append("# The bot cross-checks Naukri for the same role and applies there.")
    urls.append("# ================================================================")

    for role in ROLES:
        for term in EXPERIENCE_TERMS:
            query = f"{role} {term}".strip()
            encoded_kw = urllib.parse.quote(query)

            for loc in LINKEDIN_LOCATIONS:
                encoded_loc = urllib.parse.quote(loc)
                add(
                    f"https://www.linkedin.com/jobs/search/"
                    f"?keywords={encoded_kw}"
                    f"&location={encoded_loc}"
                    f"&{LINKEDIN_EXP_FILTER}"
                    f"&f_TPR=r604800"   # past 7 days (fresh listings only)
                )

    return urls


def main() -> None:
    lines = generate_urls()
    total_real = sum(1 for l in lines if l.startswith("http"))
    out_path = Path("d:/job-agent/jobs/urls.txt")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")

    naukri_cnt = sum(1 for l in lines if "naukri.com" in l)
    linkedin_cnt = sum(1 for l in lines if "linkedin.com" in l)

    print(f"Generated {total_real} unique URLs:")
    print(f"  Naukri  : {naukri_cnt}")
    print(f"  LinkedIn: {linkedin_cnt}")
    print(f"Saved to  : {out_path}")


if __name__ == "__main__":
    main()

