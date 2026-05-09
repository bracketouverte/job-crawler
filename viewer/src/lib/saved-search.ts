import { readFile, stat } from "node:fs/promises";
import type { JobRow, SavedSearch, MatchRunManifest } from "./types.js";
import {
  SAVED_SEARCHES_PATH,
  CRAWLER_ACTIVE_LOCK_PATH,
  CRAWLER_ACTIVE_LOCK_STALE_MS,
  SAVED_SEARCH_ANALYZER_ENABLED,
  savedSearchAnalyzerPaused,
  savedSearchAnalyzerBusy,
  activeRunIds,
  setSavedSearchAnalyzerBusy,
  setSavedSearchAnalyzerCurrent,
} from "./config.js";
import { db, jobCacheKey } from "./db.js";
import { getAnalysisCache, hasFullAnalysis } from "./analysis.js";
import { readHiddenJobs } from "./notifications.js";
import { addJobFilterConditions } from "./filters.js";
import { companyName } from "./company.js";
import {
  generateRunId,
  writeManifest,
  matchRunLogPath,
  executeMatchRun,
} from "./match-run.js";

export async function readSavedSearches(): Promise<SavedSearch[]> {
  try {
    const raw = await readFile(SAVED_SEARCHES_PATH, "utf8");
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? parsed.filter((item): item is SavedSearch => item !== null && typeof item === "object") : [];
  } catch (error) {
    console.error("saved-search analyzer: failed to read saved searches:", error);
    return [];
  }
}

export async function isCrawlerActive(): Promise<boolean> {
  try {
    const info = await stat(CRAWLER_ACTIVE_LOCK_PATH);
    return Date.now() - info.mtimeMs <= CRAWLER_ACTIVE_LOCK_STALE_MS;
  } catch {
    return false;
  }
}

export async function findNextSavedSearchJob(): Promise<{ job: JobRow; search: SavedSearch } | null> {
  const searches = await readSavedSearches();
  if (searches.length === 0) {
    return null;
  }

  const analysisCache = await getAnalysisCache();
  const hiddenJobs = await readHiddenJobs();

  for (const search of searches) {
    const { conditions, params } = addJobFilterConditions({
      title: search.title,
      location: search.location,
      company: search.company,
      sources: search.sources,
      days: search.days,
    });
    conditions.push("job_url IS NOT NULL");
    const where = `WHERE ${conditions.join(" AND ")}`;
    const batchSize = 200;
    let offset = 0;
    while (true) {
      const jobs = db
        .prepare(
          `SELECT provider, source_key, job_id, title, location, employment_type,
                  compensation, department, job_url, updated_at, posted_at, first_seen_at, last_seen_at
           FROM catalog_jobs ${where}
           ORDER BY COALESCE(posted_at, first_seen_at) DESC
           LIMIT ? OFFSET ?`,
        )
        .all(...params, batchSize, offset) as JobRow[];

      if (jobs.length === 0) break;

      for (const job of jobs) {
        const key = jobCacheKey(job);
        if (hiddenJobs.has(key) || hasFullAnalysis(analysisCache[key])) {
          continue;
        }
        return { job, search };
      }

      offset += batchSize;
    }
  }

  return null;
}

export async function runSavedSearchAnalyzerOnce(): Promise<void> {
  if (!SAVED_SEARCH_ANALYZER_ENABLED || savedSearchAnalyzerPaused || savedSearchAnalyzerBusy || activeRunIds.size > 0) {
    return;
  }
  if (await isCrawlerActive()) {
    return;
  }

  setSavedSearchAnalyzerBusy(true);
  try {
    const next = await findNextSavedSearchJob();
    if (next === null) {
      return;
    }

    const runId = generateRunId();
    const manifest: MatchRunManifest = {
      id: runId,
      status: "queued",
      created_at: new Date().toISOString(),
      started_at: null,
      finished_at: null,
      job_count: 1,
      parsed_count: 0,
      matched_count: 0,
      failed_count: 0,
      jobs: [{
        provider: next.job.provider,
        source_key: next.job.source_key,
        job_id: next.job.job_id,
        title: next.job.title,
        company: companyName(next.job),
        location: next.job.location,
        job_url: next.job.job_url,
      }],
      error: null,
      result_file: null,
      log_file: matchRunLogPath(runId),
    };

    console.log(
      `saved-search analyzer: full analysis start | search=${next.search.id ?? next.search.label ?? "saved-search"} | job=${jobCacheKey(next.job)}`,
    );
    await writeManifest(manifest);
    setSavedSearchAnalyzerCurrent({
      runId,
      jobKey: jobCacheKey(next.job),
      searchId: next.search.id ?? null,
      searchLabel: next.search.label ?? null,
      job: manifest.jobs[0]!,
      startedAt: manifest.created_at,
    });
    await executeMatchRun(runId, [next.job], "claude-ensemble");
  } catch (error) {
    console.error("saved-search analyzer error:", error);
  } finally {
    setSavedSearchAnalyzerCurrent(null);
    setSavedSearchAnalyzerBusy(false);
  }
}
