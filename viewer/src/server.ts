import express from "express";
import db from "./db.js";
import { decideJobFilters, loadFilterCriteria } from "./job-filter.js";
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
const CRAWLER_PROGRESS_PATH = process.env.CRAWLER_PROGRESS_PATH ?? join(STATE_DIR, "crawler-progress.json");
const DISCORD_WEBHOOK_URL = process.env.DISCORD_WEBHOOK_URL?.trim() ?? "";
const SCORE_NOTIFY_MIN_SCORE = parseFloat(process.env.SCORE_NOTIFY_MIN_SCORE ?? "4");
const TITLE_FILTER_URL = process.env.TITLE_FILTER_URL?.trim() ?? "";
const TARGET_TITLES_RAW = process.env.TARGET_TITLES?.trim() ?? "";
const TARGET_TITLES_PATH = process.env.TARGET_TITLES_PATH ?? join(__dirname, "../public/target-titles.json");
const TITLE_MATCH_MIN_CONFIDENCE = parseFloat(process.env.TITLE_MATCH_MIN_CONFIDENCE ?? "0.85");
const JOB_LOCATION_TYPE_RAW = process.env.JOB_LOCATION_TYPE?.trim() ?? "";
const JOB_LOCATION_METRO_RAW = process.env.JOB_LOCATION_METRO?.trim() ?? "";
const SALARY_RAW = process.env.SALARY?.trim() ?? "";
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
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  salary_period: string | null;
  salary_location: string | null;
  salary_is_estimated: boolean;
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
  title_match?: { match: boolean; reason: string; checked_at: string; family?: string | null; confidence?: number };
  filter_skip?: { factor: string; reason: string; checked_at: string; family?: string | null; confidence?: number };
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
  salary_min?: number | null;
  salary_max?: number | null;
  salary_currency?: string | null;
  salary_period?: string | null;
  salary_location?: string | null;
  salary_is_estimated?: boolean;
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
  usOnly?: boolean;
  noSalary?: boolean;
  minSalary?: number;
};

// Hybrid db (pg primary + sqlite fallback) is imported as db
async function selectJob(provider: string, source_key: string, job_id: string): Promise<JobRow | undefined> {
  const row = await db.queryOne(
    "SELECT provider, source_key, job_id, title, location, employment_type, compensation, salary_min, salary_max, salary_currency, salary_period, salary_location, salary_is_estimated, department, job_url, updated_at, posted_at, first_seen_at, last_seen_at FROM catalog_jobs WHERE provider = $1 AND source_key = $2 AND job_id = $3",
    [provider, source_key, job_id]
  );
  return row as JobRow | undefined;
}

async function persistParsedMetadata(job: JobRow, parsed: ParsedJobPost): Promise<void> {
  const location = cleanParsedText(parsed.location);
  const parsedCompensation = cleanParsedText(parsed.compensation);
  const compensation = isRealCompensation(parsedCompensation) ? parsedCompensation : null;
  if (!location && !compensation && parsed.salary_min == null) return;
  try {
    await db.query(
      `UPDATE catalog_jobs SET
        location = CASE WHEN $1 IS NOT NULL AND TRIM($1) <> '' AND (location IS NULL OR TRIM(location) = '') THEN $1 ELSE location END,
        compensation = CASE WHEN $2 IS NOT NULL AND TRIM($2) <> '' THEN $2 ELSE compensation END,
        salary_min = CASE WHEN $3 IS NOT NULL THEN $3 ELSE salary_min END,
        salary_max = CASE WHEN $4 IS NOT NULL THEN $4 ELSE salary_max END,
        salary_currency = CASE WHEN $5 IS NOT NULL THEN $5 ELSE salary_currency END,
        salary_period = CASE WHEN $6 IS NOT NULL THEN $6 ELSE salary_period END,
        salary_location = CASE WHEN $7 IS NOT NULL THEN $7 ELSE salary_location END,
        salary_is_estimated = CASE WHEN $8 IS NOT NULL THEN $8 ELSE salary_is_estimated END
       WHERE provider = $9 AND source_key = $10 AND job_id = $11`,
      [location, compensation, parsed.salary_min ?? null, parsed.salary_max ?? null, parsed.salary_currency ?? null, parsed.salary_period ?? null, parsed.salary_location ?? null, parsed.salary_is_estimated ? 1 : 0, job.provider, job.source_key, job.job_id]
    );
  } catch (e) {
    console.error("persistParsedMetadata error:", e);
  }
}

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
    usOnly?: boolean | string | null;
    noSalary?: boolean | string | null;
    minSalary?: string | number | null;
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
        conditions.push(token.exclude ? `title NOT ILIKE $${params.length + 1}` : `title ILIKE $${params.length + 1}`);
        params.push(`%${token.terms[0]}%`);
      } else {
        if (token.exclude) {
          const clauses = token.terms.map((_, j) => `title NOT ILIKE $${params.length + j + 1}`);
          conditions.push(`(${clauses.join(" AND ")})`);
          for (const t of token.terms) params.push(`%${t}%`);
        } else {
          const clauses = token.terms.map((_, j) => `title ILIKE $${params.length + j + 1}`);
          conditions.push(`(${clauses.join(" OR ")})`);
          for (const t of token.terms) params.push(`%${t}%`);
        }
      }
    }
  }

  if (location.trim()) {
    const locs = location.split(/[,]+/).map((l) => l.trim()).filter(Boolean);
    const clauses = locs.map((_, j) => `location ILIKE $${params.length + j + 1}`);
    conditions.push(`(${clauses.join(" OR ")})`);
    for (const loc of locs) params.push(`%${loc}%`);
  }

  if (company.trim()) {
    const companies = company.split(/[,]+/).map((c) => c.trim()).filter(Boolean);
    const clauses = companies.map((_, j) => `source_key ILIKE $${params.length + j + 1}`);
    conditions.push(`(${clauses.join(" OR ")})`);
    for (const comp of companies) params.push(`%${comp}%`);
  }

  if (sources.trim()) {
    const providerList = sources.split(/[,]+/).map((s) => s.trim()).filter(Boolean);
    if (providerList.length > 0) {
      const placeholders = providerList.map((_, j) => `$${params.length + j + 1}`).join(",");
      conditions.push(`provider IN (${placeholders})`);
      for (const provider of providerList) params.push(provider);
    }
  }

  if (days.trim()) {
    const n = parseInt(days, 10);
    if (!Number.isNaN(n) && n > 0) {
      const cutoff = new Date(Date.now() - n * 24 * 60 * 60 * 1000).toISOString();
      conditions.push(`COALESCE(posted_at, first_seen_at) >= $${params.length + 1}`);
      params.push(cutoff);
    }
  }

  const usOnly = typeof filters.usOnly === "boolean" ? filters.usOnly : String(filters.usOnly ?? "").trim() === "1";
  if (usOnly) {
    const usPatterns = [
      "location ILIKE '%united states%'",
      "location ILIKE '%usa%'",
      "location ILIKE '%, us%'",
      "location ILIKE '%, us,%'",
      "location ILIKE '%, al,%'", "location ILIKE '%, al %'",
      "location ILIKE '%, ak,%'", "location ILIKE '%, ak %'",
      "location ILIKE '%, az,%'", "location ILIKE '%, az %'",
      "location ILIKE '%, ar,%'", "location ILIKE '%, ar %'",
      "location ILIKE '%, ca,%'", "location ILIKE '%, ca %'",
      "location ILIKE '%, co,%'", "location ILIKE '%, co %'",
      "location ILIKE '%, ct,%'", "location ILIKE '%, ct %'",
      "location ILIKE '%, de,%'", "location ILIKE '%, de %'",
      "location ILIKE '%, fl,%'", "location ILIKE '%, fl %'",
      "location ILIKE '%, ga,%'", "location ILIKE '%, ga %'",
      "location ILIKE '%, hi,%'", "location ILIKE '%, hi %'",
      "location ILIKE '%, id,%'", "location ILIKE '%, id %'",
      "location ILIKE '%, il,%'", "location ILIKE '%, il %'",
      "location ILIKE '%, in,%'", "location ILIKE '%, in %'",
      "location ILIKE '%, ia,%'", "location ILIKE '%, ia %'",
      "location ILIKE '%, ks,%'", "location ILIKE '%, ks %'",
      "location ILIKE '%, ky,%'", "location ILIKE '%, ky %'",
      "location ILIKE '%, la,%'", "location ILIKE '%, la %'",
      "location ILIKE '%, me,%'", "location ILIKE '%, me %'",
      "location ILIKE '%, md,%'", "location ILIKE '%, md %'",
      "location ILIKE '%, ma,%'", "location ILIKE '%, ma %'",
      "location ILIKE '%, mi,%'", "location ILIKE '%, mi %'",
      "location ILIKE '%, mn,%'", "location ILIKE '%, mn %'",
      "location ILIKE '%, ms,%'", "location ILIKE '%, ms %'",
      "location ILIKE '%, mo,%'", "location ILIKE '%, mo %'",
      "location ILIKE '%, mt,%'", "location ILIKE '%, mt %'",
      "location ILIKE '%, ne,%'", "location ILIKE '%, ne %'",
      "location ILIKE '%, nv,%'", "location ILIKE '%, nv %'",
      "location ILIKE '%, nh,%'", "location ILIKE '%, nh %'",
      "location ILIKE '%, nj,%'", "location ILIKE '%, nj %'",
      "location ILIKE '%, nm,%'", "location ILIKE '%, nm %'",
      "location ILIKE '%, ny,%'", "location ILIKE '%, ny %'",
      "location ILIKE '%, nc,%'", "location ILIKE '%, nc %'",
      "location ILIKE '%, nd,%'", "location ILIKE '%, nd %'",
      "location ILIKE '%, oh,%'", "location ILIKE '%, oh %'",
      "location ILIKE '%, ok,%'", "location ILIKE '%, ok %'",
      "location ILIKE '%, or,%'", "location ILIKE '%, or %'",
      "location ILIKE '%, pa,%'", "location ILIKE '%, pa %'",
      "location ILIKE '%, ri,%'", "location ILIKE '%, ri %'",
      "location ILIKE '%, sc,%'", "location ILIKE '%, sc %'",
      "location ILIKE '%, sd,%'", "location ILIKE '%, sd %'",
      "location ILIKE '%, tn,%'", "location ILIKE '%, tn %'",
      "location ILIKE '%, tx,%'", "location ILIKE '%, tx %'",
      "location ILIKE '%, ut,%'", "location ILIKE '%, ut %'",
      "location ILIKE '%, vt,%'", "location ILIKE '%, vt %'",
      "location ILIKE '%, va,%'", "location ILIKE '%, va %'",
      "location ILIKE '%, wa,%'", "location ILIKE '%, wa %'",
      "location ILIKE '%, wv,%'", "location ILIKE '%, wv %'",
      "location ILIKE '%, wi,%'", "location ILIKE '%, wi %'",
      "location ILIKE '%, wy,%'", "location ILIKE '%, wy %'",
      "location ILIKE '%, dc,%'", "location ILIKE '%, dc %'",
    ];
    conditions.push(`(${usPatterns.join(" OR ")})`);
  }

  const noSalary = typeof filters.noSalary === "boolean" ? filters.noSalary : String(filters.noSalary ?? "").trim() === "1";
  if (noSalary) {
    conditions.push("(compensation IS NULL OR TRIM(compensation) = '')");
  }

  const minSalaryStr = String(filters.minSalary ?? "").trim();
  if (minSalaryStr) {
    const minSalary = parseInt(minSalaryStr, 10);
    if (!Number.isNaN(minSalary) && minSalary > 0) {
      conditions.push(`salary_min >= $${params.length + 1}`);
      params.push(minSalary);
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
  _analysisCacheValue = cache;
  _analysisCacheTime = Date.now();
}

let _analysisCacheValue: AnalysisCache | null = null;
let _analysisCacheTime = 0;
const ANALYSIS_CACHE_TTL_MS = 5000;

async function getAnalysisCache(): Promise<AnalysisCache> {
  if (_analysisCacheValue !== null && Date.now() - _analysisCacheTime < ANALYSIS_CACHE_TTL_MS) {
    return _analysisCacheValue;
  }
  _analysisCacheValue = await readAnalysisCache();
  _analysisCacheTime = Date.now();
  return _analysisCacheValue;
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
  const roleSummary = (analysis as { role_summary?: Record<string, unknown> } | null)?.role_summary ?? {};
  const tldr   = roleSummary.tldr   ? String(roleSummary.tldr)   : null;
  const domain = roleSummary.domain ? String(roleSummary.domain) : null;
  const embed = {
    ...(companyUrl ? { author: { name: companyUrl, url: `https://${companyUrl}` } } : {}),
    title,
    url: jobUrl || undefined,
    color: 3066993,
    ...(tldr ? { description: tldr } : {}),
    ...(thumbnailUrl ? { thumbnail: { url: thumbnailUrl } } : {}),
    fields: [
      { name: "Score", value: `${score.toFixed(1)}/5`, inline: true },
      { name: "Company", value: company || "n/a", inline: true },
      { name: "Location", value: normalizeLabel(row.location as string | null | undefined) || "n/a", inline: true },
      { name: "Mode", value: jobMode(row.location as string | null | undefined, row.employment_type as string | null | undefined), inline: true },
      { name: "Compensation", value: jobCompensation(row.compensation as string | null | undefined), inline: true },
      ...(domain ? [{ name: "Domain", value: domain, inline: true }] : []),
      { name: "Decision", value: decisionEmoji(score), inline: false },
    ],
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
    existing.pipelines[pipelineTag] = {
      analysis: row.analysis ?? null,
      analyzed_at: analyzedAt,
      run_id: runId,
      ...(row.jd_parse_error ? { jd_parse_error: String(row.jd_parse_error) } : {}),
    };
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

const PARSE_CONCURRENCY = 6;

async function writeBatchInput(runId: string, jobs: JobRow[], manifest: MatchRunManifest): Promise<MatchRunManifest> {
  await writeFile(matchRunLogPath(runId), "", "utf8");

  // Parse all jobs concurrently with a concurrency cap, preserving original order.
  let active = 0;
  let next = 0;
  const results: { parsed: ParsedJobPost; parseError: string | null }[] = new Array(jobs.length);

  await new Promise<void>((resolve) => {
    const trySchedule = (): void => {
      while (active < PARSE_CONCURRENCY && next < jobs.length) {
        const idx = next++;
        const job = jobs[idx];
        const jobLabel = `${companyName(job)} | ${job.title ?? job.job_id}`;
        active++;

        const task: Promise<void> = job.job_url
          ? appendMatchRunLog(runId, `[parse] ${jobLabel} | start | url=${job.job_url}`)
              .then(() => parseJobPost(job.job_url!))
              .then(async (parsed) => {
                await appendMatchRunLog(
                  runId,
                  `[parse] ${jobLabel} | success | provider=${parsed.provider ?? job.provider} title=${parsed.title ?? job.title ?? "n/a"}`,
                );
                persistParsedMetadata(job, parsed);
                results[idx] = { parsed, parseError: null };
              })
              .catch(async (error) => {
                const parseError = error instanceof Error ? error.message : String(error);
                await appendMatchRunLog(runId, `[parse] ${jobLabel} | failed | ${parseError}`);
                results[idx] = { parsed: {}, parseError };
              })
          : appendMatchRunLog(runId, `[parse] ${jobLabel} | failed | Missing job URL`).then(() => {
              results[idx] = { parsed: {}, parseError: "Missing job URL" };
            });

        task.then(() => {
          active--;
          if (next < jobs.length) {
            trySchedule();
          } else if (active === 0) {
            resolve();
          }
        });
      }
      if (next >= jobs.length && active === 0) resolve();
    };
    trySchedule();
  });

  let parsedCount = 0;
  let failedCount = 0;
  const lines: string[] = [];

  for (let i = 0; i < jobs.length; i++) {
    const job = jobs[i];
    const { parsed, parseError } = results[i];
    if (parseError) failedCount++; else parsedCount++;
    lines.push(
      JSON.stringify({
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
      }),
    );
  }

  await writeFile(matchRunInputPath(runId), `${lines.join("\n")}\n`, "utf8");
  return {
    ...manifest,
    parsed_count: parsedCount,
    failed_count: failedCount,
  };
}

async function executeMatchRunFromInput(runId: string, mode?: string): Promise<void> {
  const manifest = await readManifest(runId);
  if (manifest === null) return;
  activeRunIds.add(runId);
  try {
    await writeManifest({ ...manifest, status: "running", started_at: new Date().toISOString() });
    await writeFile(matchRunLogPath(runId), "", "utf8");
    const isEnsemble = mode === "claude-ensemble";
    const script = isEnsemble ? join(MATCHER_DIR, "ensemble_runner.py") : join(MATCHER_DIR, "job_fit_analyzer.py");
    const pipelineTag = isEnsemble ? "claude-ensemble" : "claude";
    await runCommand(PYTHON_BIN, [script, "--jobs-jsonl", matchRunInputPath(runId), "--results-jsonl",
      matchRunResultsPath(runId), "--profile-dir", join(MATCHER_DIR, CAREER_OPS_DIR), "--pipeline", pipelineTag],
      { env: process.env, logPrefix: `match-run ${runId}`, logFile: matchRunLogPath(runId) });
    const results = await readJsonl(matchRunResultsPath(runId)) as Array<Record<string, unknown>>;
    const matchedCount = results.filter((row) => row.status === "ok").length;
    await persistRunResults(runId, results);
    await writeManifest({ ...manifest, status: "completed", finished_at: new Date().toISOString(),
      matched_count: matchedCount, failed_count: results.length - matchedCount });
  } catch (err) {
    console.error(`executeMatchRunFromInput ${runId} error:`, err);
    await writeManifest({ ...manifest, status: "failed", finished_at: new Date().toISOString(),
      error: err instanceof Error ? err.message : String(err) });
  } finally {
    activeRunIds.delete(runId);
  }
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
  const { title, location, days, company, sources, page, limit, us_only, no_salary, min_salary, sort } = req.query as Record<string, string>;

  const pageNum = Math.max(1, parseInt(page ?? "1", 10));
  const pageSize = Math.min(500, Math.max(1, parseInt(limit ?? "50", 10)));
  const offset = (pageNum - 1) * pageSize;

  const { conditions, params } = addJobFilterConditions({ title, location, company, sources, days, usOnly: us_only, noSalary: no_salary, minSalary: min_salary });

  const where = conditions.length > 0 ? `WHERE ${conditions.join(" AND ")}` : "";

  const sortOrder = sort === "salary_desc"
    ? "ORDER BY COALESCE(salary_max, salary_min) DESC NULLS LAST, COALESCE(posted_at, first_seen_at) DESC"
    : sort === "salary_asc"
    ? "ORDER BY COALESCE(salary_min, salary_max) ASC NULLS LAST, COALESCE(posted_at, first_seen_at) DESC"
    : sort === "age_asc"
    ? "ORDER BY COALESCE(posted_at, first_seen_at) ASC"
    : "ORDER BY COALESCE(posted_at, first_seen_at) DESC";

  try {
    const analysisCache = await getAnalysisCache();
    const countRow = await db.queryOne(`SELECT COUNT(*) as n FROM catalog_jobs ${where}`, params) as { n: unknown } | null;
    const total = countRow ? parseInt(String((countRow as any).n ?? (countRow as any).count ?? 0), 10) : 0;

    const jobs = await db.query(
        `SELECT provider, source_key, job_id, title, location, employment_type,
                compensation, salary_min, salary_max, salary_currency, salary_period, salary_location, salary_is_estimated,
                department, job_url, updated_at, posted_at, first_seen_at, last_seen_at
         FROM catalog_jobs ${where}
         ${sortOrder}
         LIMIT $${params.length + 1} OFFSET $${params.length + 2}`,
        [...params, pageSize, offset]
      ) as JobRow[];

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
  const job = await selectJob(provider, source_key, job_id) as JobRow | undefined;
  if (!job) { res.status(404).json({ error: "Job not found" }); return; }
  try {
    const analysisCache = await getAnalysisCache();
    const cached = analysisCache[jobCacheKey(job)];
    res.json({ ...sanitizeJob(job), analysis: bestAnalysis(cached), pipelines: cached?.pipelines ?? {} });
  } catch (err) {
    res.status(500).json({ error: String(err) });
  }
});

app.get("/api/sources", async (_req, res) => {
  try {
    const providers = await db.query(`SELECT DISTINCT provider FROM catalog_jobs ORDER BY provider`) as { provider: string }[];

    res.json({ sources: providers.map((p) => p.provider) });
  } catch (err) {
    console.error("/api/sources error:", err);
    res.status(500).json({ error: String(err) });
  }
});

app.get("/api/stats", async (_req, res) => {
  try {
    const byProviderRaw = await db.query(`SELECT provider, COUNT(*) as count FROM catalog_jobs GROUP BY provider ORDER BY count DESC`);
    const byProvider = (byProviderRaw as Array<Record<string, unknown>>).map(r => ({ provider: r.provider as string, count: parseInt(String(r.count),10) }));
    const total = byProvider.reduce((s, r) => s + r.count, 0);
    const lastRow = await db.queryOne(`SELECT MAX(last_seen_at) as ts FROM catalog_jobs`) as { ts: string | null } | null;
    const lastSeen = lastRow?.ts ?? null;

    let crawlProgress: Record<string, unknown> | null = null;
    const active = await isCrawlerActive();
    if (active) {
      try {
        const raw = await readFile(CRAWLER_PROGRESS_PATH, "utf8");
        crawlProgress = JSON.parse(raw.trim()) as Record<string, unknown>;
      } catch {
        // progress file not yet written or unreadable
      }
    }

    res.json({ total, byProvider, lastCrawl: lastSeen, crawlActive: active, crawlProgress });
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
      const cntRow = await db.queryOne("SELECT COUNT(*) as n FROM catalog_jobs") as { n: unknown } | null;
      const total_jobs = cntRow ? parseInt(String((cntRow as any).n ?? (cntRow as any).count ?? 0),10) : 0;
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
    const row = await selectJob(item.provider, item.source_key, item.job_id) as JobRow | undefined;
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
  const job = await selectJob(provider, source_key, job_id) as JobRow | undefined;
  if (!job) { res.status(404).json({ error: "Job not found" }); return; }

  const runId = generateRunId();
  const manifest: MatchRunManifest = {
    id: runId,
    status: "queued",
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

app.get("/api/title-filter", async (_req, res) => {
  const criteria = await loadFilterCriteria({
    targetsRaw: TARGET_TITLES_RAW || undefined,
    targetsPath: TARGET_TITLES_PATH,
    locationTypesRaw: JOB_LOCATION_TYPE_RAW || undefined,
    metrosRaw: JOB_LOCATION_METRO_RAW || undefined,
    salaryRaw: SALARY_RAW || undefined,
  });
  let service: unknown = null;
  if (TITLE_FILTER_URL) {
    try {
      const base = TITLE_FILTER_URL.replace(/\/score\/?$/, "");
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 2000);
      try {
        const health = await fetch(`${base}/health`, { signal: controller.signal });
        service = await health.json();
      } finally {
        clearTimeout(timer);
      }
    } catch (err) {
      service = { status: "unreachable", error: err instanceof Error ? err.message : String(err) };
    }
  }
  res.json({
    targets: criteria.targets,
    locationTypes: criteria.locationTypes,
    metros: criteria.metros,
    salary: criteria.salary,
    minConfidence: Number.isFinite(TITLE_MATCH_MIN_CONFIDENCE) ? TITLE_MATCH_MIN_CONFIDENCE : 0.85,
    filterUrl: TITLE_FILTER_URL || null,
    service,
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
  const job = await selectJob(provider, source_key, job_id) as JobRow | undefined;
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

  const analysisCache = await getAnalysisCache();
  const hiddenJobs = await readHiddenJobs();

  for (const search of searches) {
    const { conditions, params } = addJobFilterConditions({
      title: search.title,
      location: search.location,
      company: search.company,
      sources: search.sources,
      days: search.days,
      usOnly: search.usOnly,
      noSalary: search.noSalary,
      minSalary: search.minSalary,
    });
    conditions.push("job_url IS NOT NULL");
    const where = `WHERE ${conditions.join(" AND ")}`;
    const batchSize = 200;
    let offset = 0;
    while (true) {
      const jobs = await db.query(
          `SELECT provider, source_key, job_id, title, location, employment_type,
                  compensation, salary_min, salary_max, salary_currency, salary_period, salary_location, salary_is_estimated,
                  department, job_url, updated_at, posted_at, first_seen_at, last_seen_at
           FROM catalog_jobs ${where}
           ORDER BY COALESCE(posted_at, first_seen_at) DESC
           LIMIT $${params.length + 1} OFFSET $${params.length + 2}`,
          [...params, batchSize, offset]
        ) as JobRow[];

      if (jobs.length === 0) break;

      for (const job of jobs) {
        const key = jobCacheKey(job);
        if (hiddenJobs.has(key) || hasFullAnalysis(analysisCache[key])) {
          continue;
        }
        if (analysisCache[key]?.title_match?.match === false || analysisCache[key]?.filter_skip) {
          continue;
        }
        return { job, search };
      }

      offset += batchSize;
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

    // Pre-filter: cheap System-1 gate before the expensive LLM ensemble.
    // Title (Laya sidecar) + location type + metro + salary; every factor is
    // fail-open on missing data. A definitive mismatch records a marker (so
    // the 60s loop skips it) and returns without LLM.
    const criteria = await loadFilterCriteria({
      targetsRaw: TARGET_TITLES_RAW || undefined,
      targetsPath: TARGET_TITLES_PATH,
      locationTypesRaw: JOB_LOCATION_TYPE_RAW || undefined,
      metrosRaw: JOB_LOCATION_METRO_RAW || undefined,
      salaryRaw: SALARY_RAW || undefined,
    });
    const anyFilterConfigured =
      criteria.targets.length > 0 || criteria.locationTypes.length > 0 || criteria.metros.length > 0 || criteria.salary !== null;
    if (anyFilterConfigured) {
      const decision = await decideJobFilters(next.job, criteria, {
        filterUrl: TITLE_FILTER_URL || undefined,
        minConfidence: Number.isFinite(TITLE_MATCH_MIN_CONFIDENCE) ? TITLE_MATCH_MIN_CONFIDENCE : 0.85,
      });
      if (!decision.proceed) {
        const cache = await readAnalysisCache();
        const key = jobCacheKey(next.job);
        const existing = cache[key] ?? { pipelines: {} };
        const marker = {
          factor: decision.failedFactor ?? "unknown",
          reason: decision.reason ?? "mismatch",
          checked_at: new Date().toISOString(),
          family: decision.family ?? null,
          confidence: decision.confidence,
        };
        existing.filter_skip = marker;
        if (decision.failedFactor === "title") {
          existing.title_match = {
            match: false,
            reason: decision.reason ?? "mismatch",
            checked_at: marker.checked_at,
            family: decision.family ?? null,
            confidence: decision.confidence,
          };
        }
        cache[key] = existing;
        await writeAnalysisCache(cache);
        console.log(
          `saved-search analyzer: filter skip | search=${next.search.id ?? next.search.label ?? "saved-search"} | job=${key} | factor=${marker.factor} | reason=${marker.reason} | engine=${decision.engine ?? "n/a"}`
        );
        return;
      }
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
    await Promise.all(
      entries.map(async (entry: string) => {
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
      }),
    );
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
