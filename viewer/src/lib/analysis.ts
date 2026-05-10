import { readFile, writeFile } from "node:fs/promises";
import type { AnalysisCache, CachedJobAnalysis } from "./types.js";
import { ANALYSIS_CACHE_PATH } from "./config.js";

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
  // fallback: latest by analyzed_at
  const entries = Object.values(cached.pipelines ?? {});
  if (entries.length === 0) return cached.analysis ?? null;
  entries.sort((a, b) => (b.analyzed_at ?? "").localeCompare(a.analyzed_at ?? ""));
  return entries[0].analysis;
}

export async function readAnalysisCache(): Promise<AnalysisCache> {
  try {
    const raw = await readFile(ANALYSIS_CACHE_PATH, "utf8");
    const parsed = JSON.parse(raw) as AnalysisCache;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

let _analysisCacheValue: AnalysisCache | null = null;
let _analysisCacheTime = 0;
export const ANALYSIS_CACHE_TTL_MS = 5000;

export async function writeAnalysisCache(cache: AnalysisCache): Promise<void> {
  await writeFile(ANALYSIS_CACHE_PATH, `${JSON.stringify(cache)}\n`, "utf8");
  _analysisCacheValue = cache;
  _analysisCacheTime = Date.now();
}

export async function getAnalysisCache(): Promise<AnalysisCache> {
  if (_analysisCacheValue !== null && Date.now() - _analysisCacheTime < ANALYSIS_CACHE_TTL_MS) {
    return _analysisCacheValue;
  }
  _analysisCacheValue = await readAnalysisCache();
  _analysisCacheTime = Date.now();
  return _analysisCacheValue;
}

export async function persistRunResults(
  runId: string,
  results: Array<Record<string, unknown>>,
  notifyFn: (row: Record<string, unknown>, runId: string) => Promise<boolean>,
): Promise<void> {
  const cache = await readAnalysisCache();
  const analyzedAt = new Date().toISOString();
  const notificationTasks: Array<Promise<boolean>> = [];

  for (const row of results) {
    if (row.status !== "ok") continue;
    if (typeof row.provider !== "string" || typeof row.source_key !== "string" || typeof row.job_id !== "string") {
      continue;
    }
    const key = `${row.provider}|${row.source_key}|${row.job_id}`;
    const pipelineTag = String((row.analysis as Record<string, unknown>)?.pipeline ?? "maverick");
    const existing = cache[key] ?? { pipelines: {} };
    if (!existing.pipelines) existing.pipelines = {};
    existing.pipelines[pipelineTag] = {
      analysis: row.analysis ?? null,
      analyzed_at: analyzedAt,
      run_id: runId,
      ...(row.jd_parse_error ? { jd_parse_error: String(row.jd_parse_error) } : {}),
    };
    cache[key] = existing;
    notificationTasks.push(notifyFn(row, runId));
  }

  await writeAnalysisCache(cache);
  const sent = await Promise.allSettled(notificationTasks);
  for (const result of sent) {
    if (result.status === "rejected") {
      console.error("score notification error:", result.reason);
    }
  }
}
