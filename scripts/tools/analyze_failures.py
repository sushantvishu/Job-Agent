import sqlite3

con = sqlite3.connect('jobs.db')
cur = con.cursor()

print("--- TOP FAILED REASONS ---")
for row in cur.execute("SELECT reason, count(*) FROM jobs WHERE status='failed' GROUP BY reason ORDER BY count(*) DESC LIMIT 10"):
    print(f"  [{row[1]}] {str(row[0])[:120]}")

print("\n--- TOP NEEDS_MANUAL_INPUT REASONS ---")
for row in cur.execute("SELECT reason, count(*) FROM jobs WHERE status='needs_manual_input' GROUP BY reason ORDER BY count(*) DESC LIMIT 10"):
    print(f"  [{row[1]}] {str(row[0])[:120]}")

print("\n--- ERROR REASONS ---")
for row in cur.execute("SELECT reason, count(*) FROM jobs WHERE status='error' GROUP BY reason ORDER BY count(*) DESC LIMIT 10"):
    print(f"  [{row[1]}] {str(row[0])[:120]}")

con.close()
