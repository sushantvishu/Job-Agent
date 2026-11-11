import sqlite3
c = sqlite3.connect('d:/job-agent/jobs.db')
c.row_factory = sqlite3.Row
print('Count:', c.execute("SELECT COUNT(*) FROM jobs WHERE url LIKE '%linkedin.com%' AND status IN ('shortlisted', 'needs_manual_input')").fetchone()[0])
