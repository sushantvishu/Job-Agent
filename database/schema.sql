-- ============================================================
-- Job Agent Framework — SQLite Schema Definition
-- ============================================================
-- Automatically loaded by database/init_db.py on first launch
-- ============================================================

-- Main jobs tracking table
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    company TEXT,
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    canonical_key TEXT,
    location TEXT,
    score INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'discovered',
    reason TEXT,
    red_flags TEXT,
    missing_skills TEXT,
    criteria_text TEXT,
    notes TEXT,
    applied_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Search and discovery audit log
CREATE TABLE IF NOT EXISTS search_page_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    search_key TEXT NOT NULL,
    page_key TEXT NOT NULL,
    page_url TEXT,
    status TEXT NOT NULL,
    candidates_found INTEGER NOT NULL DEFAULT 0,
    selected_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE(source, search_key, page_key)
);

-- Company seen/contact tracking
CREATE TABLE IF NOT EXISTS company_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    company_key TEXT NOT NULL UNIQUE,
    company_name TEXT,
    first_seen_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    total_applications INTEGER NOT NULL DEFAULT 0
);

-- Operational execution and audit logs
CREATE TABLE IF NOT EXISTS job_audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    level TEXT NOT NULL DEFAULT 'INFO',
    message TEXT NOT NULL,
    context_data TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

-- Indices for high performance deduplication & queries
CREATE INDEX IF NOT EXISTS idx_jobs_canonical ON jobs(canonical_key);
CREATE INDEX IF NOT EXISTS idx_jobs_url ON jobs(url);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_search_page_source ON search_page_log(source, search_key);
