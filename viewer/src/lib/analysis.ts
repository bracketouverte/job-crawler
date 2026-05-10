import { readFileSync } from "node:fs";
import type { AnalysisCache, CachedJobAnalysis, SinglePipelineResult } from "./types.js";
import { ANALYSIS_CACHE_PATH } from "./config.js";
import { db, updateAnalysisScoreStatement } from "./db.js";

// ---------------------------------------------------------------------------
// Schema bootstrap — runs synchronously at module load, idempotent
// ---------------------------------------------------------------------------

db.exec(`
  CREATE TABLE IF NOT EXISTS job_analyses (
    job_key     TEXT NOT NULL,
    pipeline    TEXT NOT NULL,
    analysis    TEXT NOT NULL,
    analyzed_at TEXT NOT NULL,
    run_id      TEXT NOT NULL,
    PRIMARY KEY (job_key, pipeline)
  );
  CREATE INDEX IF NOT EXISTS job_analyses_job_key_idx ON job_analyses(job_key);
`);

// ---------------------------------------------------------------------------
// One-time migration: import existing JSON cache into SQLite if table is empty
// ---------------------------------------------------------------------------

{
  const count = (db.prepare("SELECT COUNT(*) as n FROM job_analyses").get() as { n: number }).n;
  if (count === 0) {
    try {
      const raw = readFileSync(ANALYSIS_CACHE_PATH, "utf8");
      const parsed = JSON.parse(raw) as AnalysisCache;
      if (parsed && typeof parsed === "object") {
        const insert = db.prepare(
          `INSERT OR IGNORE INTO job_analyses (job_key, pipeline, analysis, analyzed_at, run_id)
           VALUES (@job_key, @pipeline, @analysis, @analyzed_at, @run_id)`,
        );
        db.transaction((cache: AnalysisCache) => {
          for (const [key, cached] of Object.entries(cache)) {
            if (!cached || typeof cached !== "object") continue;
            const pipelines = cached.pipelines ?? {};
            for (const [pipeline, entry] of Object.entries(pipelines)) {
              insert.run({
                job_key: key,
                pipeline,
                analysis: JSON.stringify(entry.analysis ?? null),
                analyzed_at: entry.analyzed_at ?? new Date().toISOString(),
                run_id: entry.run_id ?? "",
              });
            }
            // Legacy flat format (before pipelines field existed)
            if (Object.keys(pipelines).length === 0 && cached.analysis != null) {
              insert.run({
                job_key: key,
                pipeline: "legacy",
                analysis: JSON.stringify(cached.analysis),
                analyzed_at: cached.analyzed_at ?? new Date().toISOString(),
                run_id: cached.run_id ?? "",
              });
            }
          }
        })(parsed);
        console.log(`[analysis] migrated JSON cache → SQLite (${Object.keys(parsed).length} keys)`);
      }
    } catch {
      // No legacy JSON file or parse error — start fresh
    }
  }
}

// ---------------------------------------------------------------------------
// Pure analysis helpers
// ---------------------------------------------------------------------------

export function analysisScore5(analysis: unknown): number | null {
  if (!analysis || typeof analysis !== "object") return null;
  const value = (analysis as { score_5?: unknown }).score_5;
  const score = typeof value === "number" ? value : parseFloat(String(value ?? ""));
  return Number.isFinite(score) ? score : null;
}

export function analysisRecommendation(analysis: unknown): string {
  if (!analysis || typeof analysis !== "object") return "n/a";
  return String((analysis as { application_recommendation?: unknown }).application_recommendation ?? "n/a").replace(/_/g, " ");
}

export function hasFullAnalysis(cached: CachedJobAnalysis | undefined): boolean {
  if (!cached) return false;
  return cached.pipelines?.["claude-ensemble"] != null;
}

export function bestAnalysis(cached: CachedJobAnalysis | undefined): unknown {
  if (!cached) return null;
  if (cached.pipelines?.["claude-ensemble"]) return cached.pipelines["claude-ensemble"].analysis;
  if (cached.pipelines?.["claude"]) return cached.pipelines["claude"].analysis;
  const entries = Object.values(cached.pipelines ?? {});
  if (entries.length === 0) return cached.analysis ?? null;
  entries.sort((a, b) => (b.analyzed_at ?? "").localeCompare(a.analyzed_at ?? ""));
  return entries[0].analysis;
}

// ---------------------------------------------------------------------------
// SQLite-backed reads
// ---------------------------------------------------------------------------

type AnalysisRow = { job_key: string; pipeline: string; analysis: string; analyzed_at: string; run_id: string };

const _selectAll = db.prepare<[], AnalysisRow>(
  `SELECT job_key, pipeline, analysis, analyzed_at, run_id FROM job_analyses`,
);

const _upsert = db.prepare(
  `INSERT INTO job_analyses (job_key, pipeline, analysis, analyzed_at, run_id)
   VALUES (@job_key, @pipeline, @analysis, @analyzed_at, @run_id)
   ON CONFLICT(job_key, pipeline) DO UPDATE SET
     analysis    = excluded.analysis,
     analyzed_at = excluded.analyzed_at,
     run_id      = excluded.run_id`,
);

function rowsToCache(rows: AnalysisRow[]): AnalysisCache {
  const cache: AnalysisCache = {};
  for (const row of rows) {
    let analysis: unknown;
    try { analysis = JSON.parse(row.analysis); } catch { analysis = null; }
    const existing = cache[row.job_key] ?? { pipelines: {} };
    if (!existing.pipelines) existing.pipelines = {};
    existing.pipelines[row.pipeline] = { analysis, analyzed_at: row.analyzed_at, run_id: row.run_id };
    cache[row.job_key] = existing;
  }
  return cache;
}

export function readAnalysisCacheSync(): AnalysisCache {
  return rowsToCache(_selectAll.all());
}

export async function readAnalysisCache(): Promise<AnalysisCache> {
  return readAnalysisCacheSync();
}

// ---------------------------------------------------------------------------
// In-process TTL cache — avoids full table scan on every request
// ---------------------------------------------------------------------------

let _analysisCacheValue: AnalysisCache | null = null;
let _analysisCacheTime = 0;
export const ANALYSIS_CACHE_TTL_MS = 5000;

export function invalidateAnalysisCache(): void {
  _analysisCacheValue = null;
}

export async function writeAnalysisCache(_cache: AnalysisCache): Promise<void> {
  // No-op: writes now go directly via persistRunResults upserts.
  // Kept for API compatibility — callers that passed a full cache object now get a no-op.
}

export async function getAnalysisCache(): Promise<AnalysisCache> {
  if (_analysisCacheValue !== null && Date.now() - _analysisCacheTime < ANALYSIS_CACHE_TTL_MS) {
    return _analysisCacheValue;
  }
  _analysisCacheValue = readAnalysisCacheSync();
  _analysisCacheTime = Date.now();
  return _analysisCacheValue;
}

// ---------------------------------------------------------------------------
// Sync analysis_score to catalog_jobs after each upsert
// ---------------------------------------------------------------------------

function parseJobKey(jobKey: string): { provider: string; source_key: string; job_id: string } | null {
  const parts = jobKey.split("|");
  if (parts.length < 3) return null;
  const [provider, source_key, ...rest] = parts;
  return { provider: provider!, source_key: source_key!, job_id: rest.join("|") };
}

function writeScoreToJobRow(jobKey: string, analysis: unknown): void {
  const score = analysisScore5(analysis);
  if (score === null) return;
  const key = parseJobKey(jobKey);
  if (!key) return;
  try {
    updateAnalysisScoreStatement.run({ score, ...key });
  } catch {
    // catalog_jobs row may not exist (e.g. test data)
  }
}

// Backfill analysis_score for existing job_analyses rows that don't yet have a score in catalog_jobs
{
  const rows = db.prepare(
    `SELECT ja.job_key, ja.analysis
     FROM job_analyses ja
     JOIN catalog_jobs cj ON cj.provider || '|' || cj.source_key || '|' || cj.job_id = ja.job_key
     WHERE cj.analysis_score IS NULL
       AND ja.pipeline IN ('claude-ensemble', 'ensemble', 'claude', 'legacy', 'maverick')
     GROUP BY ja.job_key`,
  ).all() as { job_key: string; analysis: string }[];

  if (rows.length > 0) {
    db.transaction(() => {
      for (const row of rows) {
        let analysis: unknown;
        try { analysis = JSON.parse(row.analysis); } catch { continue; }
        writeScoreToJobRow(row.job_key, analysis);
      }
    })();
    console.log(`[analysis] backfilled analysis_score for ${rows.length} jobs`);
  }
}

// ---------------------------------------------------------------------------
// Persist a single pipeline result — O(1) upsert
// ---------------------------------------------------------------------------

export function persistPipelineEntry(
  jobKey: string,
  pipeline: string,
  entry: SinglePipelineResult,
): void {
  _upsert.run({
    job_key: jobKey,
    pipeline,
    analysis: JSON.stringify(entry.analysis ?? null),
    analyzed_at: entry.analyzed_at,
    run_id: entry.run_id,
  });
  writeScoreToJobRow(jobKey, entry.analysis);
  invalidateAnalysisCache();
}

// ---------------------------------------------------------------------------
// persistRunResults — O(results) upserts, no full-cache read+write
// ---------------------------------------------------------------------------

export async function persistRunResults(
  runId: string,
  results: Array<Record<string, unknown>>,
  notifyFn: (row: Record<string, unknown>, runId: string) => Promise<boolean>,
): Promise<void> {
  const analyzedAt = new Date().toISOString();
  const notificationTasks: Array<Promise<boolean>> = [];

  db.transaction(() => {
    for (const row of results) {
      if (row.status !== "ok") continue;
      if (typeof row.provider !== "string" || typeof row.source_key !== "string" || typeof row.job_id !== "string") continue;
      const key = `${row.provider}|${row.source_key}|${row.job_id}`;
      const pipelineTag = String((row.analysis as Record<string, unknown>)?.pipeline ?? "maverick");
      _upsert.run({
        job_key: key,
        pipeline: pipelineTag,
        analysis: JSON.stringify(row.analysis ?? null),
        analyzed_at: analyzedAt,
        run_id: runId,
      });
      writeScoreToJobRow(key, row.analysis);
      notificationTasks.push(notifyFn(row, runId));
    }
  })();

  invalidateAnalysisCache();

  const sent = await Promise.allSettled(notificationTasks);
  for (const result of sent) {
    if (result.status === "rejected") {
      console.error("score notification error:", result.reason);
    }
  }
}
