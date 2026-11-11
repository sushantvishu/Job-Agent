-- Migration 0006: Autonomous Inbound Recruiter Triage and Interview Tracking
CREATE TABLE IF NOT EXISTS interviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    company TEXT NOT NULL,
    role TEXT,
    intent TEXT NOT NULL, -- INTERVIEW_INVITE, TECHNICAL_ASSESSMENT, REJECTION, MORE_INFO_REQUESTED, OFFER
    status TEXT NOT NULL DEFAULT 'needs_action', -- needs_action, scheduled, completed, archived
    recruiter_name TEXT,
    recruiter_email TEXT,
    meeting_link TEXT,
    assessment_link TEXT,
    deadline_or_time TEXT,
    raw_snippet TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY(job_id) REFERENCES jobs(id)
);

CREATE INDEX IF NOT EXISTS idx_interviews_company ON interviews(company);
CREATE INDEX IF NOT EXISTS idx_interviews_intent ON interviews(intent);
CREATE INDEX IF NOT EXISTS idx_interviews_status ON interviews(status);
