import sqlite3, sys
sys.stdout.reconfigure(encoding='utf-8')
con = sqlite3.connect('jobs.db')
cur = con.cursor()
applied = cur.execute("SELECT count(1) FROM jobs WHERE status='applied'").fetchone()[0]
total = cur.execute("SELECT count(1) FROM jobs").fetchone()[0]
print(f"Applied: {applied} | Total: {total}")
print("\n--- By Status ---")
for r in cur.execute("SELECT status, count(1) FROM jobs GROUP BY status ORDER BY count(1) DESC"):
    print(f"  {r[0]}: {r[1]}")
print("\n--- Recent 5 Applied ---")
for r in cur.execute("SELECT id, company, title, source, score, applied_at FROM jobs WHERE status='applied' ORDER BY applied_at DESC LIMIT 5"):
    print(f"  #{r[0]} | {r[1]} | {r[2]} | {r[3]} | score={r[4]} | applied_at={r[5]}")
print("\n--- Recent 3 Skipped (Seniority Guard) ---")
for r in cur.execute("SELECT id, company, title, source, score, reason FROM jobs WHERE status='skipped' ORDER BY id DESC LIMIT 3"):
    print(f"  #{r[0]} | {r[1]} | {r[2]} | {r[3]} | reason={r[5]}")
print("\n--- Recent 5 Filled Pending Submit ---")
for r in cur.execute("SELECT id, company, title, source, score, notes FROM jobs WHERE status='filled_pending_submit' ORDER BY id DESC LIMIT 5"):
    print(f"  #{r[0]} | {r[1]} | {r[2]} | {r[3]} | score={r[4]} | notes={r[5]}")



