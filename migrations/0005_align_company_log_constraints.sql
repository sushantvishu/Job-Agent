-- Migration 0005: Align search_company_log schema and lookup indexes
CREATE INDEX IF NOT EXISTS idx_search_company_log_lookup 
ON search_company_log(source, search_key, company_key);
