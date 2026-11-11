-- Migration 0003: Performance Indexes for high-throughput querying
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(score);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_source_status ON jobs(source, status);
CREATE INDEX IF NOT EXISTS idx_search_page_lookup ON search_page_log(source, search_key, page_key, status);
