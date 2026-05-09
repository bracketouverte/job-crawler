import { spawn } from "node:child_process";
import { join } from "node:path";
import { appendFile, mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import type { JobRow, MatchRunManifest, ParsedJobPost, RunCommandOptions } from "./types.js";
import {
  MATCH_RUNS_DIR,
  MATCHER_DIR,
  PYTHON_BIN,
  CAREER_OPS_DIR,
  activeRunIds,
} from "./config.js";
import { db, updateParsedMetadataStatement, sanitizeJob, isRealCompensation } from "./db.js";
import { companyName } from "./company.js";
import { persistRunResults } from "./analysis.js";
import { notifyDiscordForScore } from "./notifications.js";

export function matchRunDir(runId: string): string {
  return join(MATCH_RUNS_DIR, runId);
}

export function matchRunManifestPath(runId: string): string {
  return join(matchRunDir(runId), "manifest.json");
}

export function matchRunInputPath(runId: string): string {
  return join(matchRunDir(runId), "jobs.jsonl");
}

export function matchRunResultsPath(runId: string): string {
  return join(matchRunDir(runId), "results.jsonl");
}

export function matchRunLogPath(runId: string): string {
  return join(matchRunDir(runId), "matcher.log");
}

export async function ensureMatchRunDir(runId: string): Promise<void> {
  await mkdir(matchRunDir(runId), { recursive: true });
}

export async function writeManifest(manifest: MatchRunManifest): Promise<void> {
  await ensureMatchRunDir(manifest.id);
  await writeFile(matchRunManifestPath(manifest.id), `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
}

export async function readManifest(runId: string): Promise<MatchRunManifest | null> {
  try {
    const raw = await readFile(matchRunManifestPath(runId), "utf8");
    return JSON.parse(raw) as MatchRunManifest;
  } catch {
    return null;
  }
}

export async function readJsonl(filePath: string): Promise<unknown[]> {
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

export function emitBufferedLines(
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

export async function flushPendingLine(
  state: { pending: string },
  sink: (line: string) => void,
): Promise<void> {
  if (!state.pending) return;
  sink(state.pending);
  state.pending = "";
}

export function runCommand(command: string, args: string[], options: RunCommandOptions = {}): Promise<string> {
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

export async function appendMatchRunLog(runId: string, message: string, stream: "stdout" | "stderr" = "stderr"): Promise<void> {
  const rendered = `[match-run ${runId}] ${stream}: ${message}`;
  if (stream === "stderr") {
    console.error(rendered);
  } else {
    console.log(rendered);
  }
  await appendFile(matchRunLogPath(runId), `${rendered}\n`, "utf8");
}

export async function parseJobPost(url: string): Promise<ParsedJobPost> {
  const stdout = await runCommand(PYTHON_BIN, [join(MATCHER_DIR, "job_post_parser.py"), "--url", url], {
    env: process.env,
    logStdout: false,
  });
  return JSON.parse(stdout) as ParsedJobPost;
}

export function cleanParsedText(value: unknown): string | null {
  const text = String(value ?? "").trim().replace(/\s+/g, " ");
  return text ? text : null;
}

export function persistParsedMetadata(job: JobRow, parsed: ParsedJobPost): void {
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

export function buildJdText(parsed: ParsedJobPost, job: JobRow): string {
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

export async function writeBatchInput(runId: string, jobs: JobRow[], manifest: MatchRunManifest): Promise<MatchRunManifest> {
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

export async function executeMatchRunFromInput(runId: string, mode?: string): Promise<void> {
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
    await persistRunResults(runId, results, notifyDiscordForScore);
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

export async function executeMatchRun(runId: string, jobs: JobRow[], mode?: string): Promise<void> {
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
    await persistRunResults(runId, results, notifyDiscordForScore);

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

export function generateRunId(): string {
  const timestamp = new Date().toISOString().replace(/[-:.TZ]/g, "").slice(0, 14);
  const suffix = Math.random().toString(36).slice(2, 8);
  return `run_${timestamp}_${suffix}`;
}

export async function markOrphanedRunsFailed(): Promise<void> {
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

