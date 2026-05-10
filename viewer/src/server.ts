import express from "express";
import { join } from "node:path";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";

import type { JobRow, MatchJobKey, StatsRow } from "./lib/types.js";
import { readQueue, upsertQueueItem, removeQueueItem } from "./lib/queue.js";
import { startRetryScheduler } from "./lib/retry-scheduler.js";
import {
  PORT,
  SAVED_SEARCH_ANALYZER_ENABLED,
  SAVED_SEARCH_ANALYZER_INTERVAL_MS,
  LOGO_DEV_SECRET_KEY,
  LOGO_DEV_PUBLISHABLE_KEY,
  CRAWLER_PROGRESS_PATH,
  MATCH_RUNS_DIR,
  SCORE_NOTIFY_MIN_SCORE,
  activeRunIds,
  logoDevBrandCache,
  savedSearchAnalyzerBusy,
  savedSearchAnalyzerPaused,
  savedSearchAnalyzerCurrent,
  setSavedSearchAnalyzerPaused,
} from "./lib/config.js";
import { db, selectJobStatement, jobCacheKey, sanitizeJob } from "./lib/db.js";
import { addJobFilterConditions } from "./lib/filters.js";
import { companyName, logoCacheSet } from "./lib/company.js";
import { getAnalysisCache, bestAnalysis } from "./lib/analysis.js";
import {
  readManifest,
  readJsonl,
  writeManifest,
  generateRunId,
  matchRunLogPath,
  matchRunInputPath,
  matchRunResultsPath,
  ensureMatchRunDir,
  executeMatchRun,
  executeMatchRunFromInput,
  markOrphanedRunsFailed,
  killRun,
  runIdFromItemId,
  parseJobPost,
  persistParsedMetadata,
} from "./lib/match-run.js";
import { readHiddenJobs, writeHiddenJobs } from "./lib/notifications.js";
import { isCrawlerActive, runSavedSearchAnalyzerOnce } from "./lib/saved-search.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

const app = express();

app.use(express.json({ limit: "1mb" }));
app.use(express.static(join(__dirname, "../public")));

app.get("/api/jobs", async (req, res) => {
  const { title, location, days, company, sources, page, limit, favCompanies, evaluated } = req.query as Record<string, string>;

  const pageNum = Math.max(1, parseInt(page ?? "1", 10));
  const pageSize = Math.min(500, Math.max(1, parseInt(limit ?? "50", 10)));
  const offset = (pageNum - 1) * pageSize;

  const analysisCache = await getAnalysisCache();
  const evaluatedOnly = evaluated === "1";

  const favList = favCompanies ? favCompanies.split(",").map((s) => s.trim()).filter(Boolean) : null;

  const { conditions, params } = addJobFilterConditions({ title, location, company, sources, days, favCompanies: favList });

  if (evaluatedOnly) {
    conditions.push("analysis_score IS NOT NULL AND analysis_score > 0");
  }

  const where = conditions.length > 0 ? `WHERE ${conditions.join(" AND ")}` : "";

  try {
    const total = (
      db.prepare(`SELECT COUNT(*) as n FROM catalog_jobs ${where}`).get(...params) as { n: number }
    ).n;

    const jobs = db
      .prepare(
        `SELECT provider, source_key, job_id, title, location, employment_type,
                compensation, department, job_url, updated_at, posted_at, first_seen_at, last_seen_at
         FROM catalog_jobs ${where}
         ORDER BY COALESCE(posted_at, first_seen_at) DESC
         LIMIT ? OFFSET ?`,
      )
      .all(...params, pageSize, offset) as JobRow[];

    const enrichedJobs = jobs.map((job) => {
      const cached = analysisCache[jobCacheKey(job)];
      return { ...sanitizeJob(job), analysis: bestAnalysis(cached), pipelines: cached?.pipelines ?? {} };
    });
    res.json({ total, page: pageNum, pageSize, jobs: enrichedJobs });
  } catch (err) {
    console.error("/api/jobs error:", err);
    res.status(500).json({ error: String(err) });
  }
});

app.get("/api/job", async (req, res) => {
  const { provider, source_key, job_id } = req.query as Record<string, string>;
  if (!provider || !source_key || !job_id) {
    res.status(400).json({ error: "provider, source_key, and job_id are required" });
    return;
  }
  const job = selectJobStatement.get(provider, source_key, job_id) as JobRow | undefined;
  if (!job) { res.status(404).json({ error: "Job not found" }); return; }
  try {
    const analysisCache = await getAnalysisCache();
    const cached = analysisCache[jobCacheKey(job)];
    res.json({ ...sanitizeJob(job), analysis: bestAnalysis(cached), pipelines: cached?.pipelines ?? {} });
  } catch (err) {
    res.status(500).json({ error: String(err) });
  }
});

app.get("/api/sources", (_req, res) => {
  try {
    const providers = db
      .prepare(`SELECT DISTINCT provider FROM catalog_jobs ORDER BY provider`)
      .all() as { provider: string }[];

    res.json({ sources: providers.map((p) => p.provider) });
  } catch (err) {
    console.error("/api/sources error:", err);
    res.status(500).json({ error: String(err) });
  }
});

app.get("/api/stats", (_req, res) => {
  try {
    const byProvider = db
      .prepare(`SELECT provider, COUNT(*) as count FROM catalog_jobs GROUP BY provider ORDER BY count DESC`)
      .all() as StatsRow[];

    const total = byProvider.reduce((s, r) => s + r.count, 0);

    const lastSeen = (
      db.prepare(`SELECT MAX(last_seen_at) as ts FROM catalog_jobs`).get() as { ts: string | null }
    ).ts;

    res.json({ total, byProvider, lastCrawl: lastSeen });
  } catch (err) {
    console.error("/api/stats error:", err);
    res.status(500).json({ error: String(err) });
  }
});

function nextScheduledRun(): Date {
  // Schedule: 0 8,10,12,14,16,18,20 * * * (local time)
  const hours = [8, 10, 12, 14, 16, 18, 20];
  const now = new Date();
  const todaySlots = hours.map(h => {
    const d = new Date(now);
    d.setHours(h, 0, 0, 0);
    return d;
  });
  const next = todaySlots.find(d => d > now);
  if (next) return next;
  // Roll to tomorrow's first slot
  const tomorrow = new Date(now);
  tomorrow.setDate(tomorrow.getDate() + 1);
  tomorrow.setHours(hours[0]!, 0, 0, 0);
  return tomorrow;
}

app.get("/api/crawl-status", async (_req, res) => {
  try {
    const active = await isCrawlerActive();
    if (!active) {
      const { n: total_jobs } = db.prepare("SELECT COUNT(*) as n FROM catalog_jobs").get() as { n: number };
      res.json({ active: false, next_run: nextScheduledRun().toISOString(), total_jobs });
      return;
    }
    let progress: Record<string, unknown> | null = null;
    try {
      const raw = await readFile(CRAWLER_PROGRESS_PATH, "utf8");
      progress = JSON.parse(raw.trim()) as Record<string, unknown>;
    } catch {
      // progress file not yet written or unreadable — still report active
    }
    res.json({ active: true, progress });
  } catch (err) {
    console.error("/api/crawl-status error:", err);
    res.status(500).json({ error: String(err) });
  }
});

app.get("/api/config", (_req, res) => {
  const scorers = (process.env.NVIDIA_ENSEMBLE_SCORERS || "meta/llama-4-maverick-17b-128e-instruct,moonshotai/kimi-k2-instruct,nvidia/llama-3.3-nemotron-super-49b-v1.5")
    .split(",").map((s) => s.trim().split("/").pop() ?? s.trim()).filter(Boolean);
  const synthesizer = (process.env.NVIDIA_ENSEMBLE_SYNTHESIZER || "nvidia/llama-3.3-nemotron-super-49b-v1.5")
    .trim().split("/").pop() ?? "";
  res.json({
    logoDevPublishableKey: LOGO_DEV_PUBLISHABLE_KEY || null,
    hasLogoDevBrandSearch: Boolean(LOGO_DEV_SECRET_KEY),
    matcherEnabled: true,
    ensemble: { scorers, synthesizer },
    scoreNotifyMinScore: SCORE_NOTIFY_MIN_SCORE,
  });
});

app.post("/api/match-runs", async (req, res) => {
  const { job_keys: rawJobs, mode } = req.body as { job_keys?: MatchJobKey[]; mode?: string };
  if (!Array.isArray(rawJobs) || rawJobs.length === 0) {
    res.status(400).json({ error: "job_keys is required" });
    return;
  }

  const uniqueKeys = new Map<string, MatchJobKey>();
  for (const item of rawJobs) {
    if (!item || typeof item !== "object") continue;
    if (!item.provider || !item.source_key || !item.job_id) continue;
    uniqueKeys.set(`${item.provider}|${item.source_key}|${item.job_id}`, item);
  }

  const selectedJobs: JobRow[] = [];
  for (const item of uniqueKeys.values()) {
    const row = selectJobStatement.get(item.provider, item.source_key, item.job_id) as JobRow | undefined;
    if (row) {
      selectedJobs.push(row);
    }
  }

  if (selectedJobs.length === 0) {
    res.status(404).json({ error: "No matching jobs found in catalog" });
    return;
  }

  const runId = generateRunId();
  const manifest = {
    id: runId,
    status: "queued" as const,
    created_at: new Date().toISOString(),
    started_at: null,
    finished_at: null,
    job_count: selectedJobs.length,
    parsed_count: 0,
    matched_count: 0,
    failed_count: 0,
    jobs: selectedJobs.map((job) => ({
      provider: job.provider,
      source_key: job.source_key,
      job_id: job.job_id,
      title: job.title,
      company: companyName(job),
      location: job.location,
      job_url: job.job_url,
    })),
    error: null,
    result_file: null,
    log_file: matchRunLogPath(runId),
  };

  try {
    await writeManifest(manifest);
    void executeMatchRun(runId, selectedJobs, mode);
    res.status(202).json({
      run_id: runId,
      status: manifest.status,
      job_count: manifest.job_count,
    });
  } catch (error) {
    console.error("/api/match-runs error:", error);
    res.status(500).json({ error: error instanceof Error ? error.message : String(error) });
  }
});

app.post("/api/match-runs-with-jd", async (req, res) => {
  const { provider, source_key, job_id, jd_text, mode } = req.body as {
    provider?: string; source_key?: string; job_id?: string; jd_text?: string; mode?: string;
  };
  if (!provider || !source_key || !job_id) {
    res.status(400).json({ error: "provider, source_key, and job_id are required" });
    return;
  }
  if (!jd_text || !jd_text.trim()) {
    res.status(400).json({ error: "jd_text is required" });
    return;
  }
  const job = selectJobStatement.get(provider, source_key, job_id) as JobRow | undefined;
  if (!job) { res.status(404).json({ error: "Job not found" }); return; }

  const runId = generateRunId();
  const manifest = {
    id: runId,
    status: "queued" as const,
    created_at: new Date().toISOString(),
    started_at: null,
    finished_at: null,
    job_count: 1,
    parsed_count: 1,
    matched_count: 0,
    failed_count: 0,
    jobs: [{ provider: job.provider, source_key: job.source_key, job_id: job.job_id,
      title: job.title, company: companyName(job), location: job.location, job_url: job.job_url }],
    error: null,
    result_file: null,
    log_file: matchRunLogPath(runId),
  };

  try {
    await writeManifest(manifest);
    const inputLine = JSON.stringify({
      provider: job.provider, source_key: job.source_key, job_id: job.job_id,
      title: job.title, company: companyName(job), location: job.location,
      job_url: job.job_url, url: job.job_url,
      jd_text: jd_text.trim(),
      parse_error: null,
    });
    await ensureMatchRunDir(runId);
    await writeFile(matchRunInputPath(runId), inputLine + "\n", "utf8");
    void executeMatchRunFromInput(runId, mode);
    res.status(202).json({ run_id: runId, status: "queued", job_count: 1 });
  } catch (error) {
    console.error("/api/match-runs-with-jd error:", error);
    res.status(500).json({ error: error instanceof Error ? error.message : String(error) });
  }
});

app.get("/api/match-runs/:id", async (req, res) => {
  const manifest = await readManifest(req.params.id);
  if (manifest === null) {
    res.status(404).json({ error: "Run not found" });
    return;
  }
  res.json({
    ...manifest,
    is_active: activeRunIds.has(manifest.id),
  });
});

app.get("/api/match-runs/:id/results", async (req, res) => {
  const manifest = await readManifest(req.params.id);
  if (manifest === null) {
    res.status(404).json({ error: "Run not found" });
    return;
  }

  const results = manifest.result_file ? await readJsonl(manifest.result_file) : [];
  res.json({
    run_id: manifest.id,
    status: manifest.status,
    results,
  });
});

app.get("/api/auto-analyzer", (_req, res) => {
  res.json({
    enabled: SAVED_SEARCH_ANALYZER_ENABLED,
    paused: savedSearchAnalyzerPaused,
    busy: savedSearchAnalyzerBusy,
    current: savedSearchAnalyzerCurrent,
  });
});

app.get("/api/hidden-jobs", async (_req, res) => {
  const hidden = await readHiddenJobs();
  res.json({ hidden: [...hidden] });
});

app.put("/api/hidden-jobs", async (req, res) => {
  const rawHidden = (req.body as { hidden?: unknown }).hidden;
  if (!Array.isArray(rawHidden)) {
    res.status(400).json({ error: "hidden must be an array" });
    return;
  }
  const hidden = new Set(rawHidden.filter((key): key is string => typeof key === "string" && key.trim() !== ""));
  try {
    await writeHiddenJobs(hidden);
    res.json({ hidden: [...hidden] });
  } catch (error) {
    console.error("/api/hidden-jobs error:", error);
    res.status(500).json({ error: error instanceof Error ? error.message : String(error) });
  }
});

app.post("/api/auto-analyzer", (req, res) => {
  const paused = Boolean((req.body as { paused?: unknown }).paused);
  setSavedSearchAnalyzerPaused(paused);
  res.json({
    enabled: SAVED_SEARCH_ANALYZER_ENABLED,
    paused: savedSearchAnalyzerPaused,
    busy: savedSearchAnalyzerBusy,
    current: savedSearchAnalyzerCurrent,
  });
});

app.get("/api/logo-dev/brand", async (req, res) => {
  if (!LOGO_DEV_SECRET_KEY) {
    res.json({ domain: null });
    return;
  }

  const company = String(req.query.company ?? "").trim();
  if (!company) {
    res.status(400).json({ error: "company is required" });
    return;
  }

  const cacheKey = company.toLowerCase();
  if (logoDevBrandCache.has(cacheKey)) {
    res.json({ domain: logoDevBrandCache.get(cacheKey) ?? null });
    return;
  }

  try {
    const url = new URL("https://api.logo.dev/search");
    url.searchParams.set("q", company);
    url.searchParams.set("strategy", "match");

    const response = await fetch(url, {
      headers: {
        Authorization: `Bearer ${LOGO_DEV_SECRET_KEY}`,
      },
    });

    if (!response.ok) {
      throw new Error(`Logo.dev search failed with status ${response.status}`);
    }

    const data = (await response.json()) as Array<{ domain?: string }>;
    const domain = String(data?.[0]?.domain ?? "").trim() || null;
    logoCacheSet(cacheKey, domain);
    res.json({ domain });
  } catch (err) {
    console.error("/api/logo-dev/brand error:", err);
    res.status(502).json({ error: "Logo.dev brand search failed" });
  }
});

app.get("/api/job-parsed", async (req, res) => {
  const { provider, source_key, job_id } = req.query as Record<string, string>;
  if (!provider || !source_key || !job_id) {
    res.status(400).json({ error: "provider, source_key, and job_id are required" });
    return;
  }
  const job = selectJobStatement.get(provider, source_key, job_id) as JobRow | undefined;
  if (!job) {
    res.status(404).json({ error: "Job not found" });
    return;
  }
  if (!job.job_url) {
    res.status(422).json({ error: "Job has no URL to parse" });
    return;
  }
  try {
    const parsed = await parseJobPost(job.job_url);
    persistParsedMetadata(job, parsed);
    res.json(parsed);
  } catch (err) {
    console.error("/api/job-parsed error:", err);
    res.status(502).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

app.get("/api/queue", async (_req, res) => {
  const items = await readQueue();
  res.json(items);
});

app.post("/api/queue/:id/retry", async (req, res) => {
  const { id } = req.params;
  const items = await readQueue();
  const item = items.find((i) => i.id === id);
  if (!item) {
    res.status(404).json({ error: "Queue item not found" });
    return;
  }
  const reset = {
    ...item,
    status: "todo" as const,
    attempt: 0,
    next_retry_at: undefined,
    error: undefined,
    updated_at: new Date().toISOString(),
  };
  await upsertQueueItem(reset);

  // Fire immediately (discord-only or full run)
  const isDiscordOnly = item.subtasks.length === 1 && item.subtasks[0]?.id === "discord";
  if (isDiscordOnly) {
    // Let the scheduler pick it up on next tick by marking retrying with next_retry_at = now
    await upsertQueueItem({ ...reset, status: "retrying", next_retry_at: new Date().toISOString() });
  } else {
    void executeMatchRunFromInput(runIdFromItemId(item.id), item.mode);
  }

  res.json({ ok: true });
});

app.post("/api/queue/:id/stop", async (req, res) => {
  const { id } = req.params;
  const killed = killRun(runIdFromItemId(id));
  const items = await readQueue();
  const item = items.find((i) => i.id === id);
  if (item) {
    await upsertQueueItem({
      ...item,
      status: "permanent_error",
      error: "Stopped by user",
      subtasks: item.subtasks.map((s) =>
        s.status === "running" || s.status === "todo" ? { ...s, status: "error" as const, error: "Stopped" } : s,
      ),
      updated_at: new Date().toISOString(),
    });
  }
  const runId = runIdFromItemId(id);
  const manifest = await readManifest(runId);
  if (manifest && manifest.status === "running") {
    await writeManifest({ ...manifest, status: "failed", finished_at: new Date().toISOString(), error: "Stopped by user" });
  }
  res.json({ ok: true, killed });
});

app.post("/api/queue/:id/restart", async (req, res) => {
  const { id } = req.params;
  const runId = runIdFromItemId(id);
  // Kill running process if any
  killRun(runId);
  const items = await readQueue();
  const item = items.find((i) => i.id === id);
  if (!item) {
    res.status(404).json({ error: "Queue item not found" });
    return;
  }
  // Reset attempt count and timestamps so the timer starts fresh
  const now = new Date().toISOString();
  const reset = { ...item, status: "todo" as const, attempt: 1, next_retry_at: undefined, error: undefined,
    created_at: now, updated_at: now,
    subtasks: item.subtasks.map((s) => ({ ...s, status: "todo" as const, error: undefined, started_at: undefined, finished_at: undefined })) };
  await upsertQueueItem(reset);
  void executeMatchRunFromInput(runId, item.mode);
  res.json({ ok: true });
});

app.delete("/api/queue/:id", async (req, res) => {
  const { id } = req.params;
  const runId = runIdFromItemId(id);
  killRun(runId);
  await removeQueueItem(id);
  const manifest = await readManifest(runId);
  if (manifest && (manifest.status === "running" || manifest.status === "queued")) {
    await writeManifest({ ...manifest, status: "failed", finished_at: new Date().toISOString(), error: "Deleted by user" });
  }
  res.json({ ok: true });
});

app.listen(PORT, async () => {
  await mkdir(MATCH_RUNS_DIR, { recursive: true });
  await markOrphanedRunsFailed();
  startRetryScheduler();
  console.log(`viewer listening on http://localhost:${PORT}`);
  if (SAVED_SEARCH_ANALYZER_ENABLED) {
    setTimeout(() => void runSavedSearchAnalyzerOnce(), 5000);
    setInterval(() => void runSavedSearchAnalyzerOnce(), SAVED_SEARCH_ANALYZER_INTERVAL_MS);
  }
});
