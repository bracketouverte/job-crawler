#!/usr/bin/env node
/**
 * Database initialization script
 * Creates indexes on catalog_jobs for performance optimization
 * Run this before starting the server
 */

import Database from "better-sqlite3";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CATALOG_DB = process.env.CATALOG_DB || path.join(__dirname, "../state/catalog.sqlite");

console.log(`Initializing database indexes at: ${CATALOG_DB}`);

try {
  const db = new Database(CATALOG_DB);
  
  const indexes = [
    { name: "idx_provider", sql: "CREATE INDEX IF NOT EXISTS idx_provider ON catalog_jobs(provider);" },
    { name: "idx_location", sql: "CREATE INDEX IF NOT EXISTS idx_location ON catalog_jobs(location);" },
    { name: "idx_posted_at", sql: "CREATE INDEX IF NOT EXISTS idx_posted_at ON catalog_jobs(posted_at DESC);" },
    { name: "idx_first_seen_at", sql: "CREATE INDEX IF NOT EXISTS idx_first_seen_at ON catalog_jobs(first_seen_at DESC);" },
    { name: "idx_source_key", sql: "CREATE INDEX IF NOT EXISTS idx_source_key ON catalog_jobs(source_key);" },
    { name: "idx_salary_min", sql: "CREATE INDEX IF NOT EXISTS idx_salary_min ON catalog_jobs(salary_min);" },
    { name: "idx_salary_max", sql: "CREATE INDEX IF NOT EXISTS idx_salary_max ON catalog_jobs(salary_max);" },
    { name: "idx_composite", sql: "CREATE INDEX IF NOT EXISTS idx_provider_source_job ON catalog_jobs(provider, source_key, job_id);" },
  ];
  
  let created = 0;
  for (const index of indexes) {
    try {
      db.exec(index.sql);
      console.log(`  ✓ ${index.name}`);
      created++;
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      if (msg.includes("already exists")) {
        console.log(`  - ${index.name} (already exists)`);
      } else {
        console.error(`  ✗ ${index.name}: ${msg}`);
      }
    }
  }
  
  db.close();
  console.log(`\n✓ Database initialization complete (${created} new indexes)`);
  process.exit(0);
} catch (error) {
  console.error("✗ Database initialization failed:", error);
  process.exit(1);
}
