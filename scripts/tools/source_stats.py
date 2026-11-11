import sqlite3
c = sqlite3.connect("d:/job-agent/jobs.db")
c.row_factory = sqlite3.Row

print("=== JOBS BY SOURCE ===")
for row in c.execute("SELECT source, COUNT(*) as cnt FROM jobs GROUP BY source ORDER BY cnt DESC"):
    print(f"  {row['source']}: {row['cnt']}")

print("\n=== LINKEDIN JOBS BY STATUS ===")
for row in c.execute("SELECT status, COUNT(*) as cnt FROM jobs WHERE source='linkedin' GROUP BY status ORDER BY cnt DESC"):
    print(f"  {row['status']}: {row['cnt']}")

print("\n=== NAUKRI JOBS BY STATUS ===")
for row in c.execute("SELECT status, COUNT(*) as cnt FROM jobs WHERE source='naukri' GROUP BY status ORDER BY cnt DESC"):
    print(f"  {row['status']}: {row['cnt']}")

print("\n=== LINKEDIN IN ACTIVE QUEUE (top 5) ===")
for row in c.execute("SELECT title, company, url, score FROM jobs WHERE source='linkedin' AND status='filled_pending_submit' ORDER BY score DESC LIMIT 5"):
    print(f"  [{row['score']}] {row['title']} @ {row['company']}")
    print(f"       {row['url'][:90]}")

print("\n=== LINKEDIN APPLIED (top 5) ===")
for row in c.execute("SELECT title, company, score FROM jobs WHERE source='linkedin' AND status='applied' ORDER BY score DESC LIMIT 5"):
    print(f"  [{row['score']}] {row['title']} @ {row['company']}")
