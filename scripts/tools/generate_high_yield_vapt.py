"""
generate_high_yield_vapt.py — High-Yield VAPT & Cybersecurity Master Seed Generator

Focuses 100% on high-probability tech hubs and 7–30 day freshness horizons
to maximize the ratio of active job cards found per page load.
Filters out any page already logged in search_page_log.
"""
import sqlite3
import urllib.parse
from pathlib import Path
from app.tracker import JobTracker

# 1. High-Density Master Roles
ROLES = [
    "VAPT",
    "Penetration Tester",
    "Vulnerability Assessment",
    "Application Security",
    "Application Security Engineer",
    "AppSec Analyst",
    "SOC Analyst",
    "Junior SOC Analyst",
    "SOC Analyst L1",
    "Cyber Security Analyst",
    "Junior Cyber Security Analyst",
    "Security Analyst",
    "Information Security Analyst",
    "Ethical Hacker",
    "Junior Ethical Hacker",
    "Network Security Engineer",
    "Security Operations Center",
    "VAPT Analyst",
    "Security Engineer",
    "Python Developer Security",
]

# 2. Tier-1 Tech Hubs
HUBS = [
    ("india", "India"),
    ("remote", "Remote"),
    ("bengaluru", "Bengaluru"),
    ("hyderabad", "Hyderabad"),
    ("pune", "Pune"),
    ("delhi", "Delhi"),
    ("noida", "Noida"),
    ("gurgaon", "Gurgaon"),
    ("mumbai", "Mumbai"),
    ("chennai", "Chennai"),
]

# 3. Early-Career Experience Bands
EXP_NAUKRI = ["0", "1", "2", "0,1", "0,2", "1,2", "0,3"]
EXP_LINKEDIN = ["1", "2", "3", "1,2", "2,3", "1,2,3"]

# 4. Horizons (7 days, 14 days, 30 days)
NAUKRI_AGES = [7, 14, 30]
LINKEDIN_TPRS = ["r604800", "r2592000"]  # 7 days, 30 days

con = sqlite3.connect("jobs.db")
cur = con.cursor()
logged_pages = set(r[0] for r in cur.execute("SELECT page_key FROM search_page_log WHERE status='checked'"))
con.close()

naukri_seeds = []
for role in ROLES:
    slug = role.lower().replace(" ", "-")
    kw = urllib.parse.quote_plus(role)
    for loc_n, _ in HUBS:
        for exp in EXP_NAUKRI:
            for age in NAUKRI_AGES:
                url = f"https://www.naukri.com/{slug}-jobs-in-{loc_n}?k={kw}&l={loc_n}&experience={exp}&jobAge={age}"
                key = JobTracker.search_page_key(url)
                if key not in logged_pages:
                    naukri_seeds.append(url)

linkedin_seeds = []
for role in ROLES:
    kw = urllib.parse.quote_plus(role)
    for _, loc_l in HUBS:
        loc_enc = urllib.parse.quote_plus(loc_l)
        for exp in EXP_LINKEDIN:
            for tpr in LINKEDIN_TPRS:
                exp_enc = urllib.parse.quote_plus(exp)
                url = f"https://www.linkedin.com/jobs/search/?keywords={kw}&location={loc_enc}&f_E={exp_enc}&f_TPR={tpr}"
                key = JobTracker.search_page_key(url)
                if key not in logged_pages:
                    linkedin_seeds.append(url)

# Interleave Naukri and LinkedIn 1:1
interleaved = []
max_len = max(len(naukri_seeds), len(linkedin_seeds))
for i in range(max_len):
    if i < len(naukri_seeds):
        interleaved.append(naukri_seeds[i])
    if i < len(linkedin_seeds):
        interleaved.append(linkedin_seeds[i])

out_path = Path("jobs/vapt_high_yield_priority.txt")
out_path.parent.mkdir(parents=True, exist_ok=True)
with open(out_path, "w", encoding="utf-8") as f:
    for s in interleaved:
        f.write(s + "\n")

print(f"Generated {len(interleaved)} high-yield seeds:")
print(f" - Naukri seeds: {len(naukri_seeds)}")
print(f" - LinkedIn seeds: {len(linkedin_seeds)}")
print(f"Saved to: {out_path}")

