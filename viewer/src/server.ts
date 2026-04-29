import express from "express";
import Database from "better-sqlite3";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { appendFile, mkdir, readFile, writeFile } from "node:fs/promises";

const __dirname = dirname(fileURLToPath(import.meta.url));

const DB_PATH = process.env.CATALOG_DB ?? "/app/state/catalog.sqlite";
const STATE_DIR = process.env.STATE_DIR ?? dirname(DB_PATH);
const MATCH_RUNS_DIR = process.env.MATCH_RUNS_DIR ?? join(STATE_DIR, "match-runs");
const ANALYSIS_CACHE_PATH = process.env.ANALYSIS_CACHE_PATH ?? join(STATE_DIR, "job-analysis-cache.json");
const MATCHER_DIR = process.env.MATCHER_DIR ?? "/matcher";
const PYTHON_BIN = process.env.PYTHON_BIN ?? "python3";
const CAREER_OPS_DIR = process.env.CAREER_OPS_DIR?.trim() ?? "career-ops";
const LOGO_DEV_PUBLISHABLE_KEY = process.env.LOGO_DEV_PUBLISHABLE_KEY?.trim() ?? "";
const LOGO_DEV_SECRET_KEY = process.env.LOGO_DEV_SECRET_KEY?.trim() ?? "";
const PORT = parseInt(process.env.PORT ?? "3000", 10);
const LOGO_CACHE_MAX = 2000;
const logoDevBrandCache = new Map<string, string | null>();
const activeRunIds = new Set<string>();

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
  first_seen_at: string;
  last_seen_at: string;
  analysis?: unknown;
};

type CachedJobAnalysis = {
  analysis: unknown;
  analyzed_at: string;
  run_id: string;
};

type AnalysisCache = Record<string, CachedJobAnalysis>;

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
  url?: string | null;
  provider?: string | null;
};

const db = new Database(DB_PATH, { readonly: true, fileMustExist: true });
const selectJobStatement = db.prepare(
  `SELECT provider, source_key, job_id, title, location, employment_type,
          compensation, department, job_url, updated_at, first_seen_at, last_seen_at
   FROM catalog_jobs
   WHERE provider = ? AND source_key = ? AND job_id = ?`
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

function companyName(job: Pick<JobRow, "provider" | "source_key">): string {
  if (job.provider === "workday") return job.source_key.split("/")[0] ?? job.source_key;
  return job.source_key;
}

function jobCacheKey(job: Pick<JobRow, "provider" | "source_key" | "job_id">): string {
  return `${job.provider}|${job.source_key}|${job.job_id}`;
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

async function persistRunResults(runId: string, results: Array<Record<string, unknown>>): Promise<void> {
  const cache = await readAnalysisCache();
  const analyzedAt = new Date().toISOString();

  for (const row of results) {
    if (row.status !== "ok") continue;
    if (typeof row.provider !== "string" || typeof row.source_key !== "string" || typeof row.job_id !== "string") {
      continue;
    }
    cache[`${row.provider}|${row.source_key}|${row.job_id}`] = {
      analysis: row.analysis ?? null,
      analyzed_at: analyzedAt,
      run_id: runId,
    };
  }

  await writeAnalysisCache(cache);
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

function buildJdText(parsed: ParsedJobPost, job: JobRow): string {
  const responsibilities = Array.isArray(parsed.responsibilities) ? parsed.responsibilities : [];
  const requirements = Array.isArray(parsed.requirements_summary) ? parsed.requirements_summary : [];
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
  add("Compensation", parsed.compensation ?? job.compensation);
  add("Posted datetime", parsed.posted_datetime ?? job.updated_at ?? job.first_seen_at);
  add("JD concepts", concepts.join(", "));

  if (responsibilities.length > 0) {
    sections.push(`Responsibilities:\n${responsibilities.map((item) => `- ${item}`).join("\n")}`);
  }
  if (requirements.length > 0) {
    sections.push(`Requirements:\n${requirements.map((item) => `- ${item}`).join("\n")}`);
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
      provider: job.provider,
      source_key: job.source_key,
      job_id: job.job_id,
      title: parsed.title ?? job.title,
      company: companyName(job),
      location: parsed.location ?? job.location,
      employment_type: parsed.employment_type ?? job.employment_type,
      compensation: parsed.compensation ?? job.compensation,
      workplace_type: parsed.workplace_type,
      posted_datetime: parsed.posted_datetime ?? job.updated_at ?? job.first_seen_at,
      responsibilities: parsed.responsibilities ?? [],
      requirements_summary: parsed.requirements_summary ?? [],
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

    const script = mode === "ensemble"
      ? join(MATCHER_DIR, "ensemble_runner.py")
      : join(MATCHER_DIR, "job_fit_analyzer.py");

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
  const { title, location, days, company, sources, page } = req.query as Record<string, string>;

  const pageNum = Math.max(1, parseInt(page ?? "1", 10));
  const pageSize = 50;
  const offset = (pageNum - 1) * pageSize;

  const conditions: string[] = [];
  const params: unknown[] = [];

  if (title?.trim()) {
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

  if (location?.trim()) {
    const locs = location.split(/[,]+/).map((l) => l.trim()).filter(Boolean);
    const locClauses = locs.map(() => "LOWER(location) LIKE ?");
    conditions.push(`(${locClauses.join(" OR ")})`);
    for (const loc of locs) params.push(`%${loc.toLowerCase()}%`);
  }

  if (company?.trim()) {
    const companies = company.split(/[,]+/).map((c) => c.trim()).filter(Boolean);
    const companyClauses = companies.map(() => "LOWER(source_key) LIKE ?");
    conditions.push(`(${companyClauses.join(" OR ")})`);
    for (const comp of companies) params.push(`%${comp.toLowerCase()}%`);
  }

  if (sources?.trim()) {
    const providerList = sources.split(/[,]+/).map((s) => s.trim()).filter(Boolean);
    if (providerList.length > 0) {
      const providerClauses = providerList.map(() => "provider = ?");
      conditions.push(`(${providerClauses.join(" OR ")})`);
      for (const provider of providerList) params.push(provider);
    }
  }

  if (days?.trim()) {
    const n = parseInt(days, 10);
    if (!Number.isNaN(n) && n > 0) {
      conditions.push("first_seen_at >= datetime('now', ?)");
      params.push(`-${n} days`);
    }
  }

  const where = conditions.length > 0 ? `WHERE ${conditions.join(" AND ")}` : "";

  try {
    const analysisCache = await readAnalysisCache();
    const total = (
      db.prepare(`SELECT COUNT(*) as n FROM catalog_jobs ${where}`).get(...params) as { n: number }
    ).n;

    const jobs = db
      .prepare(
        `SELECT provider, source_key, job_id, title, location, employment_type,
                compensation, department, job_url, updated_at, first_seen_at, last_seen_at
         FROM catalog_jobs ${where}
         ORDER BY first_seen_at DESC
         LIMIT ? OFFSET ?`
      )
      .all(...params, pageSize, offset) as JobRow[];

    const enrichedJobs = jobs.map((job) => ({
      ...job,
      analysis: analysisCache[jobCacheKey(job)]?.analysis ?? null,
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
    res.json({ ...job, analysis: analysisCache[jobCacheKey(job)]?.analysis ?? null });
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
    res.json(parsed);
  } catch (err) {
    console.error("/api/job-parsed error:", err);
    res.status(502).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

app.listen(PORT, async () => {
  await mkdir(MATCH_RUNS_DIR, { recursive: true });
  console.log(`viewer listening on http://localhost:${PORT}`);
});
