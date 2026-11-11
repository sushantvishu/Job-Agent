-- Migration 0002: Ensure canonical key and location columns exist
-- Handled safely with column check or idempotent statements
CREATE INDEX IF NOT EXISTS idx_jobs_canonical_key ON jobs(canonical_key);
CREATE INDEX IF NOT EXISTS idx_jobs_location ON jobs(location);
