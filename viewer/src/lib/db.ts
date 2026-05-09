import Database from "better-sqlite3";
import type { JobRow } from "./types.js";
import { DB_PATH } from "./config.js";

export const db = new Database(DB_PATH, { fileMustExist: true });
db.pragma("busy_timeout = 30000");

export const selectJobStatement = db.prepare(
  `SELECT provider, source_key, job_id, title, location, employment_type,
          compensation, department, job_url, updated_at, posted_at, first_seen_at, last_seen_at
   FROM catalog_jobs
   WHERE provider = ? AND source_key = ? AND job_id = ?`,
);

export const updateParsedMetadataStatement = db.prepare(
  `UPDATE catalog_jobs
   SET
     location = CASE
       WHEN @location IS NOT NULL AND TRIM(@location) <> '' AND (location IS NULL OR TRIM(location) = '') THEN @location
       ELSE location
     END,
     compensation = CASE
       WHEN @compensation IS NOT NULL AND TRIM(@compensation) <> '' THEN @compensation
       ELSE compensation
     END
   WHERE provider = @provider AND source_key = @source_key AND job_id = @job_id`,
);

export const selectJobUrlStatement = db.prepare(
  `SELECT job_url FROM catalog_jobs WHERE provider=? AND source_key=? AND job_id=?`,
);

export function jobCacheKey(job: Pick<JobRow, "provider" | "source_key" | "job_id">): string {
  return `${job.provider}|${job.source_key}|${job.job_id}`;
}

export function isRealCompensation(value: unknown): boolean {
  const text = String(value ?? "").trim();
  if (!text) return false;
  if (/^(req|r|jr|job)[-_]?\d+[a-z0-9-]*$/i.test(text)) return false;
  if (/^\/?job\//i.test(text)) return false;
  if (!/(salary|compensation|base pay|pay range|ote|equity|bonus|hour|annual|year|yr|[$€£]|\b\d{2,3}\s?k\b|\b\d{2,3}[,\s]\d{3}\b)/i.test(text)) {
    return false;
  }
  return /[$€£]\s?\d|\b\d{2,3}\s?k\b|\b\d{2,3}[,\s]\d{3}\b|\b\d+\s?-\s?\d+\b/i.test(text);
}

export function sanitizeJob(row: JobRow): JobRow {
  return {
    ...row,
    compensation: isRealCompensation(row.compensation) ? row.compensation : null,
  };
}
