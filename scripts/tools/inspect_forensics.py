import sqlite3
import json
import os
import re

def audit_database():
    conn = sqlite3.connect("jobs.db")
    c = conn.cursor()

    print("=" * 60)
    print("1. DATABASE JOBS SUMMARY BY STATUS")
    print("=" * 60)
    c.execute("SELECT status, count(*) FROM jobs GROUP BY status ORDER BY count(*) DESC")
    for row in c.fetchall():
        print(f"  {str(row[0]):<25}: {row[1]}")

    print("\n" + "=" * 60)
    print("2. RECENT 10 APPLIED JOBS (SUBMITTED)")
    print("=" * 60)
    c.execute("""
        SELECT id, source, company, title, score, status, applied_at, notes
        FROM jobs
        WHERE status = 'applied'
        ORDER BY applied_at DESC
        LIMIT 10
    """)
    rows = c.fetchall()
    for r in rows:
        notes = r[7] if r[7] else ""
        if len(notes) > 90:
            notes = notes[:87] + "..."
        print(f"  [Job #{r[0]}] ({r[1]}) {r[2]} | {r[3]}")
        print(f"    Score: {r[4]} | Applied At: {r[6]} | Notes: {notes}")

    print("\n" + "=" * 60)
    print("3. RECENT 5 LINKEDIN POST RECRUITER EMAILS")
    print("=" * 60)
    c.execute("""
        SELECT id, poster_name, company, role, email_to, email_subject, sent_at, status
        FROM linkedin_post_emails
        ORDER BY sent_at DESC
        LIMIT 5
    """)
    for r in c.fetchall():
        print(f"  [Email #{r[0]}] To: {r[4]} | Role: {r[3]} @ {r[2]} | Sent: {r[6]} | Status: {r[7]}")
        print(f"    Subject: {r[5]}")

    print("\n" + "=" * 60)
    print("4. SAMPLE EMAIL BODY TEXT (LAST SENT OUTREACH)")
    print("=" * 60)
    c.execute("""
        SELECT id, email_to, email_subject, email_body
        FROM linkedin_post_emails
        WHERE status = 'sent'
        ORDER BY sent_at DESC
        LIMIT 1
    """)
    last_email = c.fetchone()
    if last_email:
        print(f"  To: {last_email[1]}")
        print(f"  Subject: {last_email[2]}")
        print("  --- Email Body Snippet ---")
        lines = last_email[3].splitlines()
        for line in lines[:15]:
            print(f"    {line}")
        if len(lines) > 15:
            print("    ...")

    print("\n" + "=" * 60)
    print("5. VERIFY RECIPIENT & OUTREACH TOTALS")
    print("=" * 60)
    c.execute("SELECT count(*) FROM linkedin_post_emails WHERE status = 'sent'")
    total_sent = c.fetchone()[0]
    c.execute("SELECT count(*) FROM linkedin_post_emails WHERE status = 'sent' AND email_to NOT LIKE '%@%'")
    invalid_recipients = c.fetchone()[0]
    print(f"  Total sent recruiter outreach emails: {total_sent}")
    print(f"  Invalid recipient emails: {invalid_recipients}")

    print("\n" + "=" * 60)
    print("6. SEARCH PAGES EVALUATED")
    print("=" * 60)
    c.execute("SELECT count(*) FROM search_page_log")
    total_search_pages = c.fetchone()[0]
    print(f"  Total search pages evaluated: {total_search_pages}")

    conn.close()

if __name__ == "__main__":
    audit_database()
