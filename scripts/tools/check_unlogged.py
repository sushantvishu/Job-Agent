import sqlite3
from app.tracker import JobTracker

con = sqlite3.connect('jobs.db')
cur = con.cursor()
logged = set(r[0] for r in cur.execute("SELECT page_key FROM search_page_log WHERE status='checked'"))
con.close()

with open('jobs/vapt_search_urls.txt', 'r', encoding='utf-8') as f:
    urls = [line.strip() for line in f if line.strip()]

un = [u for u in urls if JobTracker.search_page_key(u) not in logged]
print(f"Total: {len(urls)}, Unchecked: {len(un)}")
print(f"Naukri: {sum(1 for u in un if 'naukri' in u)}")
print(f"LinkedIn: {sum(1 for u in un if 'linkedin' in u)}")
