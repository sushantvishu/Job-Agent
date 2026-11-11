import sqlite3

con = sqlite3.connect('jobs.db')
con.row_factory = sqlite3.Row
cur = con.cursor()
rows = cur.execute('''
    SELECT id, title, company, score, source, reason, url 
    FROM jobs 
    WHERE status = "filled_pending_submit" 
    ORDER BY score DESC
''').fetchall()

print(f"Total: {len(rows)}")
for r in rows:
    print(f"ID={r['id']} | Score={r['score']} | {r['title']} @ {r['company']} | {r['source']} | reason={r['reason']}")
con.close()

