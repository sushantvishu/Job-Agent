import sqlite3

con = sqlite3.connect('jobs.db')
cur = con.cursor()
rows = cur.execute("SELECT company, title, url, reason FROM jobs WHERE reason LIKE '%No fillable form fields detected%' LIMIT 5").fetchall()
for row in rows:
    print('Company:', row[0], '| Title:', row[1])
    print('URL:', row[2])
    print('Reason:', row[3])
    print('-'*50)
con.close()
