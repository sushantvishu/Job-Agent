import sqlite3

c = sqlite3.connect('d:/job-agent/jobs.db')

# Reset filled_pending_submit and error/failed so the bot retries with the new submit button improvements
c.execute("UPDATE jobs SET status='shortlisted' WHERE status IN ('filled_pending_submit')")
c.execute("UPDATE jobs SET status='shortlisted' WHERE status IN ('failed', 'error')")
c.commit()

rows = c.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall()
for s, n in rows:
    print(f"  {s}: {n}")
print("DB reset done.")
