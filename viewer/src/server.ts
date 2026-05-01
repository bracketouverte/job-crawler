import express from "express";
import Database from "better-sqlite3";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { appendFile, mkdir, readdir, readFile, stat, writeFile } from "node:fs/promises";

const __dirname = dirname(fileURLToPath(import.meta.url));

const DB_PATH = process.env.CATALOG_DB ?? "/app/state/catalog.sqlite";
const STATE_DIR = process.env.STATE_DIR ?? dirname(DB_PATH);
const MATCH_RUNS_DIR = process.env.MATCH_RUNS_DIR ?? join(STATE_DIR, "match-runs");
const ANALYSIS_CACHE_PATH = process.env.ANALYSIS_CACHE_PATH ?? join(STATE_DIR, "job-analysis-cache.json");
const HIDDEN_JOBS_PATH = process.env.HIDDEN_JOBS_PATH ?? join(STATE_DIR, "hidden-jobs.json");
const SCORE_NOTIFICATIONS_PATH = process.env.SCORE_NOTIFICATIONS_PATH ?? join(STATE_DIR, "score-notifications.json");
const MATCHER_DIR = process.env.MATCHER_DIR ?? "/matcher";
const PYTHON_BIN = process.env.PYTHON_BIN ?? "python3";
const CAREER_OPS_DIR = process.env.CAREER_OPS_DIR?.trim() ?? "career-ops";
const LOGO_DEV_PUBLISHABLE_KEY = process.env.LOGO_DEV_PUBLISHABLE_KEY?.trim() ?? "";
const LOGO_DEV_SECRET_KEY = process.env.LOGO_DEV_SECRET_KEY?.trim() ?? "";
const PORT = parseInt(process.env.PORT ?? "3000", 10);
const SAVED_SEARCH_ANALYZER_ENABLED = process.env.SAVED_SEARCH_ANALYZER_ENABLED !== "0";
const SAVED_SEARCH_ANALYZER_INTERVAL_MS = parseInt(process.env.SAVED_SEARCH_ANALYZER_INTERVAL_MS ?? "60000", 10);
const SAVED_SEARCHES_PATH = process.env.SAVED_SEARCHES_PATH ?? join(__dirname, "../public/saved-searches.json");
const CRAWLER_ACTIVE_LOCK_PATH = process.env.CRAWLER_ACTIVE_LOCK_PATH ?? join(STATE_DIR, "crawler-active.lock");
const CRAWLER_ACTIVE_LOCK_STALE_MS = parseInt(process.env.CRAWLER_ACTIVE_LOCK_STALE_MS ?? "7200000", 10);
const DISCORD_WEBHOOK_URL = process.env.DISCORD_WEBHOOK_URL?.trim() ?? "";
const SCORE_NOTIFY_MIN_SCORE = parseFloat(process.env.SCORE_NOTIFY_MIN_SCORE ?? "4");
const LOGO_CACHE_MAX = 2000;
const logoDevBrandCache = new Map<string, string | null>();
const activeRunIds = new Set<string>();
let savedSearchAnalyzerBusy = false;
let savedSearchAnalyzerPaused = false;
let savedSearchAnalyzerCurrent: {
  runId: string;
  jobKey: string;
  searchId: string | null;
  searchLabel: string | null;
  job: CartJobPayload;
  startedAt: string;
} | null = null;

function logoCacheSet(key: string, value: string | null): void {
  if (logoDevBrandCache.size >= LOGO_CACHE_MAX) {
    logoDevBrandCache.delete(logoDevBrandCache.keys().next().value!);
  }
  logoDevBrandCache.set(key, value);
}

type JobRow = {
  provider: string;
  source_key: string;
  job_id: string;
  title: string | null;
  location: string | null;
  employment_type: string | null;
  compensation: string | null;
  department: string | null;
  job_url: string | null;
  updated_at: string | null;
  posted_at: string | null;
  first_seen_at: string;
  last_seen_at: string;
  analysis?: unknown;
};

type SinglePipelineResult = {
  analysis: unknown;
  analyzed_at: string;
  run_id: string;
};

type CachedJobAnalysis = {
  pipelines: Record<string, SinglePipelineResult>;
  // keep old fields for backward compat read
  analysis?: unknown;
  analyzed_at?: string;
  run_id?: string;
};

type AnalysisCache = Record<string, CachedJobAnalysis>;

type HiddenJobsState = {
  hidden: string[];
  updated_at: string;
};

type ScoreNotificationsState = {
  sent: Record<string, { score_5: number; notified_at: string; run_id: string }>;
};

type TitleTokenGroup = {
  terms: string[];
  exclude: boolean;
};

type StatsRow = {
  provider: string;
  count: number;
};

type MatchJobKey = {
  provider: string;
  source_key: string;
  job_id: string;
};

type CartJobPayload = MatchJobKey & {
  title?: string | null;
  company?: string | null;
  location?: string | null;
  job_url?: string | null;
};

type MatchRunManifest = {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  job_count: number;
  parsed_count: number;
  matched_count: number;
  failed_count: number;
  jobs: CartJobPayload[];
  error: string | null;
  result_file: string | null;
  log_file: string | null;
};

type ParsedJobPost = {
  title?: string | null;
  jd_concepts?: string[];
  posted_datetime?: string | null;
  location?: string | null;
  compensation?: string | null;
  workplace_type?: string | null;
  employment_type?: string | null;
  responsibilities?: string[];
  requirements_summary?: string[];
  must_have_requirements?: string[];
  nice_to_have_requirements?: string[];
  technical_tools_mentioned?: string[];
  url?: string | null;
  provider?: string | null;
};

type SavedSearch = {
  id?: string;
  label?: string;
  title?: string;
  location?: string;
  company?: string;
  days?: string | number;
  sources?: string[];
};

const db = new Database(DB_PATH, { fileMustExist: true });
db.pragma("busy_timeout = 30000");
const selectJobStatement = db.prepare(
  `SELECT provider, source_key, job_id, title, location, employment_type,
          compensation, department, job_url, updated_at, posted_at, first_seen_at, last_seen_at
   FROM catalog_jobs
   WHERE provider = ? AND source_key = ? AND job_id = ?`
);
const updateParsedMetadataStatement = db.prepare(
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
   WHERE provider = @provider AND source_key = @source_key AND job_id = @job_id`
);

// Returns an array of token groups with exclude flags.
// Single-item group = AND bare word. Multi-item group = OR group (AND-ed with rest).
// Prefix with - to negate: "product -(owner,builder)" → include product, exclude owner/builder
// Input: "product (manager,owner) -(growth,marketing)"
function parseTitleQuery(input: string): TitleTokenGroup[] {
  const tokens: TitleTokenGroup[] = [];
  const str = input.trim();
  let i = 0;
  while (i < str.length) {
    const isNegated = str[i] === "-";
    if (isNegated) i++;

    if (str[i] === "(") {
      const end = str.indexOf(")", i);
      const inner = end === -1 ? str.slice(i + 1) : str.slice(i + 1, end);
      const terms = inner.split(",").map((t) => t.trim().toLowerCase()).filter(Boolean);
      if (terms.length > 0) tokens.push({ terms, exclude: isNegated });
      i = end === -1 ? str.length : end + 1;
    } else {
      const match = str.slice(i).match(/^[^\s(]+/);
      if (match) {
        const word = match[0].toLowerCase();
        if (word) tokens.push({ terms: [word], exclude: isNegated });
        i += match[0].length;
      } else {
        i++;
      }
    }
  }
  return tokens;
}

function addJobFilterConditions(
  filters: {
    title?: string | number | null;
    location?: string | number | null;
    company?: string | number | null;
    sources?: string | string[] | null;
    days?: string | number | null;
  },
): { conditions: string[]; params: unknown[] } {
  const conditions: string[] = [];
  const params: unknown[] = [];
  const title = String(filters.title ?? "");
  const location = String(filters.location ?? "");
  const company = String(filters.company ?? "");
  const days = String(filters.days ?? "");
  const sources = Array.isArray(filters.sources) ? filters.sources.join(",") : String(filters.sources ?? "");

  if (title.trim()) {
    const tokens = parseTitleQuery(title);
    for (const token of tokens) {
      if (token.terms.length === 1) {
        conditions.push(token.exclude ? "LOWER(title) NOT LIKE ?" : "LOWER(title) LIKE ?");
        params.push(`%${token.terms[0]}%`);
      } else {
        if (token.exclude) {
          const notClauses = token.terms.map(() => "LOWER(title) NOT LIKE ?");
          conditions.push(`(${notClauses.join(" AND ")})`);
          for (const t of token.terms) params.push(`%${t}%`);
        } else {
          const orClauses = token.terms.map(() => "LOWER(title) LIKE ?");
          conditions.push(`(${orClauses.join(" OR ")})`);
          for (const t of token.terms) params.push(`%${t}%`);
        }
      }
    }
  }

  if (location.trim()) {
    const locs = location.split(/[,]+/).map((l) => l.trim()).filter(Boolean);
    const locClauses = locs.map(() => "LOWER(location) LIKE ?");
    conditions.push(`(${locClauses.join(" OR ")})`);
    for (const loc of locs) params.push(`%${loc.toLowerCase()}%`);
  }

  if (company.trim()) {
    const companies = company.split(/[,]+/).map((c) => c.trim()).filter(Boolean);
    const companyClauses = companies.map(() => "LOWER(source_key) LIKE ?");
    conditions.push(`(${companyClauses.join(" OR ")})`);
    for (const comp of companies) params.push(`%${comp.toLowerCase()}%`);
  }

  if (sources.trim()) {
    const providerList = sources.split(/[,]+/).map((s) => s.trim()).filter(Boolean);
    if (providerList.length > 0) {
      const providerClauses = providerList.map(() => "provider = ?");
      conditions.push(`(${providerClauses.join(" OR ")})`);
      for (const provider of providerList) params.push(provider);
    }
  }

  if (days.trim()) {
    const n = parseInt(days, 10);
    if (!Number.isNaN(n) && n > 0) {
      conditions.push("COALESCE(posted_at, first_seen_at) >= datetime('now', ?)");
      params.push(`-${n} days`);
    }
  }

  return { conditions, params };
}

function companyName(job: Pick<JobRow, "provider" | "source_key">): string {
  if (job.provider === "workday") return job.source_key.split("/")[0] ?? job.source_key;
  return job.source_key;
}

function normalizeLabel(value: string | null | undefined): string {
  return String(value ?? "").trim().replace(/\s+/g, " ");
}

function jobMode(location: string | null | undefined, employmentType: string | null | undefined): string {
  const normalizedLocation = normalizeLabel(location);
  const normalizedEmploymentType = normalizeLabel(employmentType);
  const combined = `${normalizedLocation} ${normalizedEmploymentType}`.toLowerCase();

  if (/\bremote\b/.test(combined)) return "Remote";
  if (/\bhybrid\b/.test(combined)) return "Hybrid";
  if (/\bonsite\b|\bon-site\b|\bin-office\b|\boffice\b/.test(combined)) return "On-site";

  return normalizedLocation || normalizedEmploymentType || "n/a";
}

function jobCompensation(compensation: string | null | undefined): string {
  return normalizeLabel(compensation) || "n/a";
}

function decisionEmoji(score: number): string {
  if (score >= 4.75) return "🌟 Top pick";
  if (score >= 4.5) return "🎯 Strong match";
  if (score > 4.2) return "⚡ Quick apply";
  return "✅ Worth applying";
}

function companyLogoUrl(company: string): string | null {
  if (!LOGO_DEV_PUBLISHABLE_KEY) {
    return null;
  }

  const normalizedCompany = normalizeLabel(company);
  if (!normalizedCompany) {
    return null;
  }

  const cachedDomain = logoDevBrandCache.get(normalizedCompany.toLowerCase());
  if (cachedDomain) {
    return `https://img.logo.dev/${encodeURIComponent(cachedDomain)}?token=${encodeURIComponent(LOGO_DEV_PUBLISHABLE_KEY)}&size=64&format=png&fallback=404`;
  }

  return `https://img.logo.dev/name/${encodeURIComponent(normalizedCompany)}?token=${encodeURIComponent(LOGO_DEV_PUBLISHABLE_KEY)}&size=64&format=png&fallback=404`;
}

function companyWebsite(company: string): string | null {
  const normalizedCompany = normalizeLabel(company);
  if (!normalizedCompany) {
    return null;
  }

  const cachedDomain = logoDevBrandCache.get(normalizedCompany.toLowerCase());
  if (cachedDomain) {
    return `https://${cachedDomain}`;
  }

  return null;
}

function jobCacheKey(job: Pick<JobRow, "provider" | "source_key" | "job_id">): string {
  return `${job.provider}|${job.source_key}|${job.job_id}`;
}

function isRealCompensation(value: unknown): boolean {
  const text = String(value ?? "").trim();
  if (!text) return false;
  if (/^(req|r|jr|job)[-_]?\d+[a-z0-9-]*$/i.test(text)) return false;
  if (/^\/?job\//i.test(text)) return false;
  if (!/(salary|compensation|base pay|pay range|ote|equity|bonus|hour|annual|year|yr|[$€£]|\b\d{2,3}\s?k\b|\b\d{2,3}[,\s]\d{3}\b)/i.test(text)) {
    return false;
  }
  return /[$€£]\s?\d|\b\d{2,3}\s?k\b|\b\d{2,3}[,\s]\d{3}\b|\b\d+\s?-\s?\d+\b/i.test(text);
}

function sanitizeJob(row: JobRow): JobRow {
  return {
    ...row,
    compensation: isRealCompensation(row.compensation) ? row.compensation : null,
  };
}

function hasFullAnalysis(cached: CachedJobAnalysis | undefined): boolean {
  if (!cached) return false;
  return cached.pipelines?.["claude-ensemble"] != null;
}

function bestAnalysis(cached: CachedJobAnalysis | undefined): unknown {
  if (!cached) return null;
  if (cached.pipelines?.["claude-ensemble"]) return cached.pipelines["claude-ensemble"].analysis;
  if (cached.pipelines?.["claude"]) return cached.pipelines["claude"].analysis;
  // fallback: latest by analyzed_at
  const entries = Object.values(cached.pipelines ?? {});
  if (entries.length === 0) return cached.analysis ?? null;
  entries.sort((a, b) => (b.analyzed_at ?? "").localeCompare(a.analyzed_at ?? ""));
  return entries[0].analysis;
}

function matchRunDir(runId: string): string {
  return join(MATCH_RUNS_DIR, runId);
}

function matchRunManifestPath(runId: string): string {
  return join(matchRunDir(runId), "manifest.json");
}

function matchRunInputPath(runId: string): string {
  return join(matchRunDir(runId), "jobs.jsonl");
}

function matchRunResultsPath(runId: string): string {
  return join(matchRunDir(runId), "results.jsonl");
}

function matchRunLogPath(runId: string): string {
  return join(matchRunDir(runId), "matcher.log");
}

async function ensureMatchRunDir(runId: string): Promise<void> {
  await mkdir(matchRunDir(runId), { recursive: true });
}

async function writeManifest(manifest: MatchRunManifest): Promise<void> {
  await ensureMatchRunDir(manifest.id);
  await writeFile(matchRunManifestPath(manifest.id), `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
}

async function readManifest(runId: string): Promise<MatchRunManifest | null> {
  try {
    const raw = await readFile(matchRunManifestPath(runId), "utf8");
    return JSON.parse(raw) as MatchRunManifest;
  } catch {
    return null;
  }
}

async function readJsonl(filePath: string): Promise<unknown[]> {
  try {
    const raw = await readFile(filePath, "utf8");
    return raw
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => JSON.parse(line) as unknown);
  } catch {
    return [];
  }
}

async function readAnalysisCache(): Promise<AnalysisCache> {
  try {
    const raw = await readFile(ANALYSIS_CACHE_PATH, "utf8");
    const parsed = JSON.parse(raw) as AnalysisCache;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

async function writeAnalysisCache(cache: AnalysisCache): Promise<void> {
  await writeFile(ANALYSIS_CACHE_PATH, `${JSON.stringify(cache, null, 2)}\n`, "utf8");
}

async function readHiddenJobs(): Promise<Set<string>> {
  try {
    const raw = await readFile(HIDDEN_JOBS_PATH, "utf8");
    const parsed = JSON.parse(raw) as Partial<HiddenJobsState>;
    return new Set(Array.isArray(parsed.hidden) ? parsed.hidden.filter((key): key is string => typeof key === "string") : []);
  } catch {
    return new Set();
  }
}

async function writeHiddenJobs(hidden: Set<string>): Promise<void> {
  await writeFile(
    HIDDEN_JOBS_PATH,
    `${JSON.stringify({ hidden: [...hidden].sort(), updated_at: new Date().toISOString() }, null, 2)}\n`,
    "utf8",
  );
}

async function readScoreNotifications(): Promise<ScoreNotificationsState> {
  try {
    const raw = await readFile(SCORE_NOTIFICATIONS_PATH, "utf8");
    const parsed = JSON.parse(raw) as Partial<ScoreNotificationsState>;
    return { sent: parsed.sent && typeof parsed.sent === "object" ? parsed.sent : {} };
  } catch {
    return { sent: {} };
  }
}

async function writeScoreNotifications(state: ScoreNotificationsState): Promise<void> {
  await writeFile(SCORE_NOTIFICATIONS_PATH, `${JSON.stringify(state, null, 2)}\n`, "utf8");
}

function analysisScore5(analysis: unknown): number | null {
  if (!analysis || typeof analysis !== "object") return null;
  const value = (analysis as { score_5?: unknown }).score_5;
  const score = typeof value === "number" ? value : parseFloat(String(value ?? ""));
  return Number.isFinite(score) ? score : null;
}

function analysisRecommendation(analysis: unknown): string {
  if (!analysis || typeof analysis !== "object") return "n/a";
  return String((analysis as { application_recommendation?: unknown }).application_recommendation ?? "n/a").replace(/_/g, " ");
}

async function notifyDiscordForScore(row: Record<string, unknown>, runId: string): Promise<boolean> {
  if (!DISCORD_WEBHOOK_URL || !Number.isFinite(SCORE_NOTIFY_MIN_SCORE)) {
    return false;
  }
  const analysis = row.analysis;
  const score = analysisScore5(analysis);
  if (score === null || score < SCORE_NOTIFY_MIN_SCORE) {
    return false;
  }
  if (typeof row.provider !== "string" || typeof row.source_key !== "string" || typeof row.job_id !== "string") {
    return false;
  }

  const key = `${row.provider}|${row.source_key}|${row.job_id}`;
  const notifications = await readScoreNotifications();
  if (notifications.sent[key]?.score_5 >= score) {
    return false;
  }

  const title = String(row.title ?? "Job");
  const company = String(row.company ?? row.source_key);
  const jobUrl = String(row.job_url ?? row.url ?? "");
  const thumbnailUrl = companyLogoUrl(company);
  const companyUrl = companyWebsite(company);
  const embed = {
    title,
    url: jobUrl || undefined,
    color: 3066993,
    ...(thumbnailUrl ? { thumbnail: { url: thumbnailUrl } } : {}),
    fields: [
      { name: "Score", value: `${score.toFixed(1)}/5`, inline: true },
      { name: "Company", value: company || "n/a", inline: true },
      { name: "Location", value: normalizeLabel(row.location as string | null | undefined) || "n/a", inline: true },
      { name: "Mode", value: jobMode(row.location as string | null | undefined, row.employment_type as string | null | undefined), inline: true },
      { name: "Compensation", value: jobCompensation(row.compensation as string | null | undefined), inline: true },
      { name: "Decision", value: decisionEmoji(score), inline: false },
    ],
    ...(companyUrl ? { footer: { text: companyUrl } } : {}),
  };

  const response = await fetch(DISCORD_WEBHOOK_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: "Job Scanner",
      embeds: [embed],
      allowed_mentions: { parse: [] },
    }),
  });

  if (!response.ok) {
    throw new Error(`Discord webhook failed with status ${response.status}`);
  }

  notifications.sent[key] = {
    score_5: score,
    notified_at: new Date().toISOString(),
    run_id: runId,
  };
  await writeScoreNotifications(notifications);
  return true;
}

async function persistRunResults(runId: string, results: Array<Record<string, unknown>>): Promise<void> {
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
    existing.pipelines[pipelineTag] = { analysis: row.analysis ?? null, analyzed_at: analyzedAt, run_id: runId };
    cache[key] = existing;
    notificationTasks.push(notifyDiscordForScore(row, runId));
  }

  await writeAnalysisCache(cache);
  const sent = await Promise.allSettled(notificationTasks);
  for (const result of sent) {
    if (result.status === "rejected") {
      console.error("score notification error:", result.reason);
    }
  }
}

type RunCommandOptions = {
  cwd?: string;
  env?: NodeJS.ProcessEnv;
  logPrefix?: string;
  logFile?: string;
  logStdout?: boolean;
  logStderr?: boolean;
};

function emitBufferedLines(
  chunk: string,
  state: { pending: string },
  sink: (line: string) => void,
): void {
  const combined = state.pending + chunk;
  const parts = combined.split(/\r?\n/);
  state.pending = parts.pop() ?? "";
  for (const part of parts) {
    sink(part);
  }
}

async function flushPendingLine(
  state: { pending: string },
  sink: (line: string) => void,
): Promise<void> {
  if (!state.pending) return;
  sink(state.pending);
  state.pending = "";
}

function runCommand(command: string, args: string[], options: RunCommandOptions = {}): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: options.env,
      stdio: ["ignore", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";
    const stdoutState = { pending: "" };
    const stderrState = { pending: "" };
    const logPrefix = options.logPrefix?.trim();
    const logFile = options.logFile;
    const logStdout = options.logStdout ?? true;
    const logStderr = options.logStderr ?? true;
    const logTasks: Array<Promise<unknown>> = [];

    const writeRunLog = (stream: "stdout" | "stderr", line: string): void => {
      if ((stream === "stdout" && !logStdout) || (stream === "stderr" && !logStderr)) {
        return;
      }
      const rendered = logPrefix ? `[${logPrefix}] ${stream}: ${line}` : `${stream}: ${line}`;
      if (stream === "stderr") {
        console.error(rendered);
      } else {
        console.log(rendered);
      }
      if (logFile) {
        logTasks.push(appendFile(logFile, `${rendered}\n`, "utf8"));
      }
    };

    child.stdout.on("data", (chunk) => {
      const text = chunk.toString();
      stdout += text;
      emitBufferedLines(text, stdoutState, (line) => writeRunLog("stdout", line));
    });
    child.stderr.on("data", (chunk) => {
      const text = chunk.toString();
      stderr += text;
      emitBufferedLines(text, stderrState, (line) => writeRunLog("stderr", line));
    });
    child.on("error", reject);
    child.on("close", async (code) => {
      try {
        await flushPendingLine(stdoutState, (line) => writeRunLog("stdout", line));
        await flushPendingLine(stderrState, (line) => writeRunLog("stderr", line));
        await Promise.allSettled(logTasks);
      } catch (error) {
        console.error("runCommand log flush error:", error);
      }

      if (code === 0) {
        resolve(stdout);
        return;
      }
      reject(new Error(stderr.trim() || stdout.trim() || `${command} exited with code ${code ?? "unknown"}`));
    });
  });
}

async function appendMatchRunLog(runId: string, message: string, stream: "stdout" | "stderr" = "stderr"): Promise<void> {
  const rendered = `[match-run ${runId}] ${stream}: ${message}`;
  if (stream === "stderr") {
    console.error(rendered);
  } else {
    console.log(rendered);
  }
  await appendFile(matchRunLogPath(runId), `${rendered}\n`, "utf8");
}

async function parseJobPost(url: string): Promise<ParsedJobPost> {
  const stdout = await runCommand(PYTHON_BIN, [join(MATCHER_DIR, "job_post_parser.py"), "--url", url], {
    env: process.env,
    logStdout: false,
  });
  return JSON.parse(stdout) as ParsedJobPost;
}

function cleanParsedText(value: unknown): string | null {
  const text = String(value ?? "").trim().replace(/\s+/g, " ");
  return text ? text : null;
}

function persistParsedMetadata(job: JobRow, parsed: ParsedJobPost): void {
  const location = cleanParsedText(parsed.location);
  const parsedCompensation = cleanParsedText(parsed.compensation);
  const compensation = isRealCompensation(parsedCompensation) ? parsedCompensation : null;
  if (!location && !compensation) {
    return;
  }

  try {
    updateParsedMetadataStatement.run({
      provider: job.provider,
      source_key: job.source_key,
      job_id: job.job_id,
      location,
      compensation,
    });
  } catch (error) {
    console.error("persistParsedMetadata error:", error);
  }
}

function buildJdText(parsed: ParsedJobPost, job: JobRow): string {
  const responsibilities = Array.isArray(parsed.responsibilities) ? parsed.responsibilities : [];
  const requirements = Array.isArray(parsed.requirements_summary) ? parsed.requirements_summary : [];
  const mustHave = Array.isArray(parsed.must_have_requirements) ? parsed.must_have_requirements : requirements;
  const niceToHave = Array.isArray(parsed.nice_to_have_requirements) ? parsed.nice_to_have_requirements : [];
  const technicalTools = Array.isArray(parsed.technical_tools_mentioned) ? parsed.technical_tools_mentioned : [];
  const concepts = Array.isArray(parsed.jd_concepts) ? parsed.jd_concepts : [];

  const sections: string[] = [];

  const add = (label: string, value: unknown): void => {
    const rendered = String(value ?? "").trim();
    if (!rendered) return;
    sections.push(`${label}: ${rendered}`);
  };

  add("Title", parsed.title ?? job.title);
  add("Company", companyName(job));
  add("Provider", job.provider);
  add("Location", parsed.location ?? job.location);
  add("Employment type", parsed.employment_type ?? job.employment_type);
  add("Workplace type", parsed.workplace_type);
  add("Compensation", isRealCompensation(parsed.compensation) ? parsed.compensation : sanitizeJob(job).compensation);
  add("Posted datetime", parsed.posted_datetime ?? job.posted_at ?? job.updated_at ?? job.first_seen_at);
  add("JD concepts", concepts.join(", "));
  add("Technical tools mentioned", technicalTools.join(", "));

  if (responsibilities.length > 0) {
    sections.push(`Responsibilities:\n${responsibilities.map((item) => `- ${item}`).join("\n")}`);
  }
  if (mustHave.length > 0) {
    sections.push(`Requirements:\n${mustHave.map((item) => `- ${item}`).join("\n")}`);
  }
  if (niceToHave.length > 0) {
    sections.push(`Nice-to-have:\n${niceToHave.map((item) => `- ${item}`).join("\n")}`);
  }

  return sections.join("\n\n");
}

async function writeBatchInput(runId: string, jobs: JobRow[], manifest: MatchRunManifest): Promise<MatchRunManifest> {
  const lines: string[] = [];
  let parsedCount = 0;
  let failedCount = 0;

  await writeFile(matchRunLogPath(runId), "", "utf8");

  for (const job of jobs) {
    let parsed: ParsedJobPost = {};
    let parseError: string | null = null;
    const jobLabel = `${companyName(job)} | ${job.title ?? job.job_id}`;

    if (job.job_url) {
      try {
        await appendMatchRunLog(runId, `[parse] ${jobLabel} | start | url=${job.job_url}`);
        parsed = await parseJobPost(job.job_url);
        parsedCount += 1;
        await appendMatchRunLog(
          runId,
          `[parse] ${jobLabel} | success | provider=${parsed.provider ?? job.provider} title=${parsed.title ?? job.title ?? "n/a"}`,
        );
        persistParsedMetadata(job, parsed);
      } catch (error) {
        parseError = error instanceof Error ? error.message : String(error);
        failedCount += 1;
        await appendMatchRunLog(runId, `[parse] ${jobLabel} | failed | ${parseError}`);
      }
    } else {
      parseError = "Missing job URL";
      failedCount += 1;
      await appendMatchRunLog(runId, `[parse] ${jobLabel} | failed | ${parseError}`);
    }

    const payload = {
      ...sanitizeJob(job),
      title: parsed.title ?? job.title,
      company: companyName(job),
      location: parsed.location ?? job.location,
      employment_type: parsed.employment_type ?? job.employment_type,
      compensation: isRealCompensation(parsed.compensation) ? parsed.compensation : sanitizeJob(job).compensation,
      workplace_type: parsed.workplace_type,
      posted_datetime: parsed.posted_datetime ?? job.posted_at ?? job.updated_at ?? job.first_seen_at,
      responsibilities: parsed.responsibilities ?? [],
      requirements_summary: parsed.requirements_summary ?? [],
      must_have_requirements: parsed.must_have_requirements ?? parsed.requirements_summary ?? [],
      nice_to_have_requirements: parsed.nice_to_have_requirements ?? [],
      technical_tools_mentioned: parsed.technical_tools_mentioned ?? [],
      jd_concepts: parsed.jd_concepts ?? [],
      job_url: job.job_url,
      url: job.job_url,
      jd_text: buildJdText(parsed, job),
      parse_error: parseError,
    };
    lines.push(JSON.stringify(payload));
  }

  await writeFile(matchRunInputPath(runId), `${lines.join("\n")}\n`, "utf8");
  return {
    ...manifest,
    parsed_count: parsedCount,
    failed_count: failedCount,
  };
}

async function executeMatchRun(runId: string, jobs: JobRow[], mode?: string): Promise<void> {
  const manifest = await readManifest(runId);
  if (manifest === null) {
    return;
  }

  activeRunIds.add(runId);

  try {
    const runningManifest: MatchRunManifest = {
      ...manifest,
      status: "running",
      started_at: new Date().toISOString(),
    };
    await writeManifest(runningManifest);

    const preparedManifest = await writeBatchInput(runId, jobs, runningManifest);
    await writeManifest(preparedManifest);

    const isEnsemble = mode === "claude-ensemble";
    const script = isEnsemble
      ? join(MATCHER_DIR, "ensemble_runner.py")
      : join(MATCHER_DIR, "job_fit_analyzer.py");
    const pipelineTag = isEnsemble ? "claude-ensemble" : "claude";

    await runCommand(
      PYTHON_BIN,
      [
        script,
        "--jobs-jsonl",
        matchRunInputPath(runId),
        "--results-jsonl",
        matchRunResultsPath(runId),
        "--profile-dir",
        join(MATCHER_DIR, CAREER_OPS_DIR),
        "--pipeline",
        pipelineTag,
      ],
      {
        env: process.env,
        logPrefix: `match-run ${runId}`,
        logFile: matchRunLogPath(runId),
      }
    );

    const results = await readJsonl(matchRunResultsPath(runId)) as Array<Record<string, unknown>>;
    const matchedCount = results.filter((row) => row.status === "ok").length;
    const failedCount = results.length - matchedCount;
    await persistRunResults(runId, results);

    await writeManifest({
      ...preparedManifest,
      status: "completed",
      finished_at: new Date().toISOString(),
      matched_count: matchedCount,
      failed_count: Math.max(preparedManifest.failed_count, failedCount),
      result_file: matchRunResultsPath(runId),
      log_file: matchRunLogPath(runId),
      error: null,
    });
  } catch (error) {
    await writeManifest({
      ...manifest,
      status: "failed",
      finished_at: new Date().toISOString(),
      error: error instanceof Error ? error.message : String(error),
      result_file: matchRunResultsPath(runId),
      log_file: matchRunLogPath(runId),
    });
  } finally {
    activeRunIds.delete(runId);
  }
}

function generateRunId(): string {
  const timestamp = new Date().toISOString().replace(/[-:.TZ]/g, "").slice(0, 14);
  const suffix = Math.random().toString(36).slice(2, 8);
  return `run_${timestamp}_${suffix}`;
}

const app = express();

app.use(express.json({ limit: "1mb" }));
app.use(express.static(join(__dirname, "../public")));

app.get("/api/jobs", async (req, res) => {
  const { title, location, days, company, sources, page, limit } = req.query as Record<string, string>;

  const pageNum = Math.max(1, parseInt(page ?? "1", 10));
  const pageSize = Math.min(500, Math.max(1, parseInt(limit ?? "50", 10)));
  const offset = (pageNum - 1) * pageSize;

  const { conditions, params } = addJobFilterConditions({ title, location, company, sources, days });

  const where = conditions.length > 0 ? `WHERE ${conditions.join(" AND ")}` : "";

  try {
    const analysisCache = await readAnalysisCache();
    const total = (
      db.prepare(`SELECT COUNT(*) as n FROM catalog_jobs ${where}`).get(...params) as { n: number }
    ).n;

    const jobs = db
      .prepare(
        `SELECT provider, source_key, job_id, title, location, employment_type,
                compensation, department, job_url, updated_at, posted_at, first_seen_at, last_seen_at
         FROM catalog_jobs ${where}
         ORDER BY COALESCE(posted_at, first_seen_at) DESC
         LIMIT ? OFFSET ?`
      )
      .all(...params, pageSize, offset) as JobRow[];

    const enrichedJobs = jobs.map((job) => ({
      ...sanitizeJob(job),
      analysis: bestAnalysis(analysisCache[jobCacheKey(job)]),
      pipelines: analysisCache[jobCacheKey(job)]?.pipelines ?? {},
    }));

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
    const analysisCache = await readAnalysisCache();
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

app.get("/api/config", (_req, res) => {
  res.json({
    logoDevPublishableKey: LOGO_DEV_PUBLISHABLE_KEY || null,
    hasLogoDevBrandSearch: Boolean(LOGO_DEV_SECRET_KEY),
    matcherEnabled: true,
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
  const manifest: MatchRunManifest = {
    id: runId,
    status: "queued",
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
  savedSearchAnalyzerPaused = paused;
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

async function readSavedSearches(): Promise<SavedSearch[]> {
  try {
    const raw = await readFile(SAVED_SEARCHES_PATH, "utf8");
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? parsed.filter((item): item is SavedSearch => item !== null && typeof item === "object") : [];
  } catch (error) {
    console.error("saved-search analyzer: failed to read saved searches:", error);
    return [];
  }
}

async function isCrawlerActive(): Promise<boolean> {
  try {
    const info = await stat(CRAWLER_ACTIVE_LOCK_PATH);
    return Date.now() - info.mtimeMs <= CRAWLER_ACTIVE_LOCK_STALE_MS;
  } catch {
    return false;
  }
}

async function findNextSavedSearchJob(): Promise<{ job: JobRow; search: SavedSearch } | null> {
  const searches = await readSavedSearches();
  if (searches.length === 0) {
    return null;
  }

  const analysisCache = await readAnalysisCache();
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
    const jobs = db
      .prepare(
        `SELECT provider, source_key, job_id, title, location, employment_type,
                compensation, department, job_url, updated_at, posted_at, first_seen_at, last_seen_at
         FROM catalog_jobs ${where}
         ORDER BY COALESCE(posted_at, first_seen_at) DESC`
      )
      .all(...params) as JobRow[];

    for (const job of jobs) {
      const key = jobCacheKey(job);
      if (hiddenJobs.has(key) || hasFullAnalysis(analysisCache[key])) {
        continue;
      }
      return { job, search };
    }
  }

  return null;
}

async function runSavedSearchAnalyzerOnce(): Promise<void> {
  if (!SAVED_SEARCH_ANALYZER_ENABLED || savedSearchAnalyzerPaused || savedSearchAnalyzerBusy || activeRunIds.size > 0) {
    return;
  }
  if (await isCrawlerActive()) {
    return;
  }

  savedSearchAnalyzerBusy = true;
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
      `saved-search analyzer: full analysis start | search=${next.search.id ?? next.search.label ?? "saved-search"} | job=${jobCacheKey(next.job)}`
    );
    await writeManifest(manifest);
    savedSearchAnalyzerCurrent = {
      runId,
      jobKey: jobCacheKey(next.job),
      searchId: next.search.id ?? null,
      searchLabel: next.search.label ?? null,
      job: manifest.jobs[0]!,
      startedAt: manifest.created_at,
    };
    await executeMatchRun(runId, [next.job], "claude-ensemble");
  } catch (error) {
    console.error("saved-search analyzer error:", error);
  } finally {
    savedSearchAnalyzerCurrent = null;
    savedSearchAnalyzerBusy = false;
  }
}

async function markOrphanedRunsFailed(): Promise<void> {
  try {
    const entries = await readdir(MATCH_RUNS_DIR);
    for (const entry of entries) {
      const manifestPath = join(MATCH_RUNS_DIR, entry, "manifest.json");
      try {
        const raw = await readFile(manifestPath, "utf8");
        const manifest = JSON.parse(raw) as MatchRunManifest;
        if (manifest.status === "running") {
          await writeFile(
            manifestPath,
            `${JSON.stringify({ ...manifest, status: "failed", finished_at: new Date().toISOString(), error: "orphaned: server restarted" }, null, 2)}\n`,
            "utf8",
          );
        }
      } catch { /* skip unreadable manifests */ }
    }
  } catch { /* match-runs dir may not exist yet */ }
}

app.listen(PORT, async () => {
  await mkdir(MATCH_RUNS_DIR, { recursive: true });
  await markOrphanedRunsFailed();
  console.log(`viewer listening on http://localhost:${PORT}`);
  if (SAVED_SEARCH_ANALYZER_ENABLED) {
    setTimeout(() => void runSavedSearchAnalyzerOnce(), 5000);
    setInterval(() => void runSavedSearchAnalyzerOnce(), SAVED_SEARCH_ANALYZER_INTERVAL_MS);
  }
});
