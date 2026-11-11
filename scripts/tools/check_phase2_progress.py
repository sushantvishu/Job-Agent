import sqlite3
from app.tracker import JobTracker

con = sqlite3.connect('jobs.db')
cur = con.cursor()
logged = set(r[0] for r in cur.execute("SELECT page_key FROM search_page_log WHERE status='checked'"))
con.close()

with open('jobs/vapt_phase2_priority.txt', 'r', encoding='utf-8') as f:
    seeds = [l.strip() for l in f if l.strip()]

un = [s for s in seeds if JobTracker.search_page_key(s) not in logged]
print(f"Total seeds in vapt_phase2_priority.txt: {len(seeds):,}")
print(f"Already swept and logged: {len(seeds) - len(un):,}")
print(f"Remaining fresh seeds: {len(un):,}")

