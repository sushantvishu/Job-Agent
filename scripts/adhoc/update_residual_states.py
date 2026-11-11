import sqlite3

conn = sqlite3.connect('d:/job-agent/jobs.db')
c = conn.cursor()

# Update ID 87 and 2014
c.execute("UPDATE jobs SET status = 'failed', reason = 'Job posting expired/closed (redirected to vacancy directory)' WHERE id = 87")
c.execute("UPDATE jobs SET status = 'failed', reason = 'Job posting expired on Naukri (redirected to generic search)' WHERE id = 2014")
conn.commit()

c.execute("SELECT status, count(*) FROM jobs GROUP BY status")
print("=== CURRENT DATABASE TOTALS ===")
for r in c.fetchall():
    print(f"  {r[0]}: {r[1]}")

conn.close()

