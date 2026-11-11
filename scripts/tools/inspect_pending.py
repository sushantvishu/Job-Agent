import sqlite3

con = sqlite3.connect('jobs.db')
con.row_factory = sqlite3.Row
cur = con.cursor()
rows = cur.execute('SELECT id, title, company, score, source, reason, url FROM jobs WHERE status = "filled_pending_submit" ORDER BY score DESC').fetchall()
print(f"Total in filled_pending_submit: {len(rows)}")
for r in rows:
    reason = (r['reason'] or '')[:50].replace('\n', ' ')
    print(f"[{r['id']}] Score {r['score']} | {r['title']} @ {r['company']} | src: {r['source']} | reason: {reason} | url: {r['url']}")

