-- PostgreSQL schema for job catalog
-- Complete schema matching SQLite with all 24 columns

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS catalog_jobs (
  provider TEXT NOT NULL,
  source_key TEXT NOT NULL,
  job_id TEXT NOT NULL,
  title TEXT,
  location TEXT,
  employment_type TEXT,
  compensation TEXT,
  department TEXT,
  office TEXT,
  language TEXT,
  updated_at TIMESTAMPTZ,
  job_url TEXT,
  fetched_at TIMESTAMPTZ,
  first_seen_at TIMESTAMPTZ DEFAULT NOW(),
  last_seen_at TIMESTAMPTZ DEFAULT NOW(),
  seen_run_id TEXT,
  raw_json TEXT,
  salary_min NUMERIC,
  salary_max NUMERIC,
  posted_at TIMESTAMPTZ,
  salary_currency TEXT,
  salary_period TEXT,
  salary_location TEXT,
  salary_is_estimated SMALLINT DEFAULT 0,
  
  PRIMARY KEY (provider, source_key, job_id)
);

-- Performance indexes for common queries
CREATE INDEX IF NOT EXISTS idx_provider ON catalog_jobs(provider);
CREATE INDEX IF NOT EXISTS idx_location ON catalog_jobs(location);
CREATE INDEX IF NOT EXISTS idx_posted_at ON catalog_jobs(posted_at DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_first_seen_at ON catalog_jobs(first_seen_at DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_source_key ON catalog_jobs(source_key);
CREATE INDEX IF NOT EXISTS idx_salary_min ON catalog_jobs(salary_min);
CREATE INDEX IF NOT EXISTS idx_salary_max ON catalog_jobs(salary_max);

-- Composite indexes for common filter combinations
CREATE INDEX IF NOT EXISTS idx_posted_at_provider ON catalog_jobs(posted_at DESC NULLS LAST, provider);
CREATE INDEX IF NOT EXISTS idx_first_seen_at_provider ON catalog_jobs(first_seen_at DESC NULLS LAST, provider);

-- Full-text search index on title and location (kept for tsvector queries)
CREATE INDEX IF NOT EXISTS idx_title_search ON catalog_jobs USING GIN(to_tsvector('english', title));
CREATE INDEX IF NOT EXISTS idx_location_search ON catalog_jobs USING GIN(to_tsvector('english', location));

-- Trigram indexes for ILIKE %...% queries (used by viewer filters)
CREATE INDEX IF NOT EXISTS idx_title_trgm ON catalog_jobs USING GIN(title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_location_trgm ON catalog_jobs USING GIN(location gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_source_key_trgm ON catalog_jobs USING GIN(source_key gin_trgm_ops);

-- Additional indexes for postgres catalog-store
CREATE INDEX IF NOT EXISTS catalog_jobs_seen_run_id_idx ON catalog_jobs(seen_run_id);
CREATE INDEX IF NOT EXISTS catalog_jobs_last_seen_at_idx ON catalog_jobs(last_seen_at);
