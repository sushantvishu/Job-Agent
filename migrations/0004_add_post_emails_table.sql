-- Migration 0004: Recruiter outreach and LinkedIn hiring post tracking
CREATE TABLE IF NOT EXISTS linkedin_post_emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_url TEXT NOT NULL,
    poster_name TEXT,
    company TEXT,
    role TEXT,
    email_to TEXT NOT NULL,
    email_subject TEXT,
    sent_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    reason TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE(post_url, email_to)
);

CREATE INDEX IF NOT EXISTS idx_post_emails_status ON linkedin_post_emails(status);
CREATE INDEX IF NOT EXISTS idx_post_emails_email_to ON linkedin_post_emails(email_to);
