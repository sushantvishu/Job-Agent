CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    company TEXT,
    title TEXT,
    url TEXT NOT NULL UNIQUE,
    score INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'scouted',
    reason TEXT,
    red_flags TEXT,
    missing_skills TEXT,
    applied_at TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    canonical_key TEXT,
    criteria_text TEXT,
    expansion_audit TEXT,
    location TEXT
);

CREATE TABLE IF NOT EXISTS search_company_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    search_key TEXT NOT NULL DEFAULT '',
    company_key TEXT NOT NULL DEFAULT '',
    company TEXT,
    title TEXT,
    url TEXT,
    status TEXT,
    first_seen_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    seen_count INTEGER NOT NULL DEFAULT 1,
    UNIQUE(source, search_key, company_key)
);

CREATE TABLE IF NOT EXISTS search_page_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    search_key TEXT NOT NULL,
    page_key TEXT NOT NULL,
    page_url TEXT,
    status TEXT NOT NULL,
    candidates_found INTEGER NOT NULL DEFAULT 0,
    selected_count INTEGER NOT NULL DEFAULT 0,
    skipped_seen_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE(source, search_key, page_key)
);
