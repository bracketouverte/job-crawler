-- Database index creation script for job catalog
-- Run this in SQLite to speed up queries

-- Indexes for common filters
CREATE INDEX IF NOT EXISTS idx_provider ON catalog_jobs(provider);
CREATE INDEX IF NOT EXISTS idx_location ON catalog_jobs(location);
CREATE INDEX IF NOT EXISTS idx_posted_at ON catalog_jobs(posted_at);
CREATE INDEX IF NOT EXISTS idx_first_seen_at ON catalog_jobs(first_seen_at);
CREATE INDEX IF NOT EXISTS idx_source_key ON catalog_jobs(source_key);

-- Composite indexes for common filter combinations
CREATE INDEX IF NOT EXISTS idx_posted_at_provider ON catalog_jobs(posted_at DESC, provider);
CREATE INDEX IF NOT EXISTS idx_first_seen_at_provider ON catalog_jobs(first_seen_at DESC, provider);

-- Indexes for the composite key lookups
CREATE INDEX IF NOT EXISTS idx_provider_source_job ON catalog_jobs(provider, source_key, job_id);
