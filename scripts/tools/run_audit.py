import sqlite3
import os
from pathlib import Path

# 1. DB Stats
con = sqlite3.connect('jobs.db')
cur = con.cursor()
status_counts = dict(cur.execute("SELECT status, count(*) FROM jobs GROUP BY status").fetchall())
page_count = cur.execute("SELECT count(*) FROM search_page_log").fetchone()[0]
email_counts = dict(cur.execute("SELECT status, count(*) FROM linkedin_post_emails GROUP BY status").fetchall())

# Recent 5 applied
recent_applied = cur.execute(
    "SELECT title, company, score, applied_at, url FROM jobs WHERE status='applied' ORDER BY applied_at DESC LIMIT 5"
).fetchall()

# Staged (filled_pending_submit)
staged = cur.execute(
    "SELECT title, company, score, url FROM jobs WHERE status='filled_pending_submit' ORDER BY id DESC LIMIT 5"
).fetchall()
con.close()

# 2. Browser lock check
lock_file = Path('browser-profile/SingletonLock')
lock_exists = lock_file.exists()

# 3. Phone Link SMS check
phone_db_dirs = [
    Path(os.path.expanduser('~')) / 'AppData/Local/Packages/Microsoft.YourPhone_8wekyb3d8bbwe/LocalCache/Indexed'
]
sms_count = 0
found_dbs = []
for p in phone_db_dirs:
    if p.exists():
        for db in p.rglob('phone.db'):
            found_dbs.append(str(db))
            try:
                p_con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
                c = p_con.cursor()
                cnt = c.execute("SELECT count(*) FROM message").fetchone()[0]
                sms_count += cnt
                p_con.close()
            except Exception as e:
                pass

print("=== AUDIT SUMMARY ===")
print("Jobs Breakdown:", status_counts)
print("Search Pages Logged:", page_count)
print("LinkedIn Post Emails:", email_counts)
print("Browser SingletonLock Active:", lock_exists)
print(f"Phone Link DBs: {len(found_dbs)} found, {sms_count} SMS messages indexed")
print("\nRecent Applied:")
for r in recent_applied:
    print(f" - {r[0]} @ {r[1]} [Score: {r[2]}] at {r[3]}")
print("\nStaged (filled_pending_submit):")
for s in staged:
    print(f" - {s[0]} @ {s[1]} [Score: {s[2]}]")
