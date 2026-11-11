import sqlite3

c = sqlite3.connect('d:/job-agent/jobs.db')
c.row_factory = sqlite3.Row

print('=== QUEUE STATUS ===')
for row in c.execute('SELECT status, COUNT(*) FROM jobs GROUP BY status ORDER BY COUNT(*) DESC'):
    print(f'{row[0]}: {row[1]}')

print()
print('=== TOP 30 PENDING SUBMIT JOBS (by score) ===')
for row in c.execute('SELECT title, company, url, score FROM jobs WHERE status = "filled_pending_submit" ORDER BY score DESC LIMIT 30'):
    print(f'[{row["score"]}] {row["title"]} @ {row["company"]}')
    print(f'    {row["url"][:100]}')

print()
print('=== NEEDS MANUAL INPUT ===')
for row in c.execute('SELECT title, company, url, score FROM jobs WHERE status = "needs_manual_input" ORDER BY score DESC LIMIT 20'):
    print(f'[{row["score"]}] {row["title"]} @ {row["company"]}')
    print(f'    {row["url"][:100]}')

