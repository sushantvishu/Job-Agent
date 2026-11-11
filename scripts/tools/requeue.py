import sqlite3
conn = sqlite3.connect('jobs.db')
c = conn.cursor()
c.execute('UPDATE jobs SET status=\'shortlisted\', score=100 WHERE status=\'filled_pending_submit\'')
conn.commit()
print(f'Updated {c.rowcount} jobs.')
conn.close()
