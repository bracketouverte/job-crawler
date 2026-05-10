import { spawn } from "node:child_process";
import { join } from "node:path";
import { appendFile, mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import type { JobRow, MatchRunManifest, ParsedJobPost, RunCommandOptions, QueueItem, QueueSubtask, QueueTaskStatus } from "./types.js";
import {
  MATCH_RUNS_DIR,
  MATCHER_DIR,
  PYTHON_BIN,
  CAREER_OPS_DIR,
  activeRunIds,
  activeRunProcesses,
} from "./config.js";
import { db, updateParsedMetadataStatement, sanitizeJob, isRealCompensation } from "./db.js";
import { companyName } from "./company.js";
import { persistRunResults } from "./analysis.js";
import { notifyDiscordForScore } from "./notifications.js";
import { readQueue, upsertQueueItem } from "./queue.js";

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
    const onLine = options.onLine;
    options.onSpawn?.(child);
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
      onLine?.(line);
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

  const effectiveMode = mode ?? "claude-ensemble";
  const now = new Date().toISOString();

  // Build one QueueItem per job using the same composite ID scheme as executeMatchRun.
  // On retry the existing items are found and their attempt counter preserved.
  const existingItems = await readQueue();
  const manifestJobs = manifest.jobs.length > 0 ? manifest.jobs : [{ provider: "", source_key: runId, job_id: runId, title: "Unknown job", company: "" }];

  const queueItems: QueueItem[] = manifestJobs.map((job) => {
    const jobKey = `${job.provider}|${job.source_key}|${job.job_id}`;
    const itemId = `${runId}:${jobKey}`;
    const existing = existingItems.find((i) => i.id === itemId);
    const base: QueueItem = existing ?? {
      id: itemId,
      job_key: jobKey,
      title: job.title ?? "Unknown job",
      company: job.company ?? "",
      mode: effectiveMode,
      status: "running",
      subtasks: buildSubtasks(effectiveMode),
      attempt: 1,
      max_attempts: 3,
      created_at: now,
      updated_at: now,
    };
    return {
      ...base,
      status: "running" as QueueTaskStatus,
      subtasks: base.subtasks.map((s) => ({ ...s, status: "todo" as QueueTaskStatus, error: undefined, started_at: undefined, finished_at: undefined })),
      updated_at: now,
    };
  });

  await Promise.all(queueItems.map(upsertQueueItem));

  const perJobHandlers = queueItems.map((qi, idx) => {
    const job = manifestJobs[idx];
    const label = `${job?.company ?? qi.company} | ${job?.title ?? qi.title}`;
    let current = qi;
    return makeLogLineHandler(current, label, (updated) => {
      current = updated;
      queueItems[idx] = updated;
      upsertQueueItem(updated).catch(() => {});
    });
  });
  const logLineHandler = makeBatchLogLineHandler(perJobHandlers);

  const markDiscordRunning = (): void => {
    for (let i = 0; i < queueItems.length; i++) {
      queueItems[i] = { ...queueItems[i], subtasks: queueItems[i].subtasks.map((s) => s.id === "discord" ? { ...s, status: "running" as QueueTaskStatus, started_at: new Date().toISOString() } : s), updated_at: new Date().toISOString() };
      upsertQueueItem(queueItems[i]).catch(() => {});
    }
  };

  const markAllDone = (scoreByJobKey?: Map<string, number>): void => {
    for (let i = 0; i < queueItems.length; i++) {
      const score = scoreByJobKey?.get(queueItems[i].job_key);
      queueItems[i] = { ...queueItems[i], status: "done", ...(score !== undefined ? { score } : {}), subtasks: queueItems[i].subtasks.map((s) => s.id === "discord" ? { ...s, status: "done" as QueueTaskStatus, finished_at: new Date().toISOString() } : s), updated_at: new Date().toISOString() };
      upsertQueueItem(queueItems[i]).catch(() => {});
    }
  };

  const markAllFailed = (errMsg: string, isPermanent: boolean, nextAttempt: number): void => {
    for (let i = 0; i < queueItems.length; i++) {
      queueItems[i] = {
        ...queueItems[i],
        attempt: nextAttempt,
        status: isPermanent ? "permanent_error" : "retrying",
        next_retry_at: isPermanent ? undefined : new Date(Date.now() + 30 * 2 ** nextAttempt * 1000).toISOString(),
        error: errMsg,
        subtasks: queueItems[i].subtasks.map((s) => s.status === "todo" || s.status === "running" ? { ...s, status: "error" as QueueTaskStatus } : s),
        updated_at: new Date().toISOString(),
      };
      upsertQueueItem(queueItems[i]).catch(() => {});
    }
  };

  try {
    await writeManifest({ ...manifest, status: "running", started_at: new Date().toISOString() });
    await writeFile(matchRunLogPath(runId), "", "utf8");
    const isEnsemble = effectiveMode === "claude-ensemble";
    const script = isEnsemble ? join(MATCHER_DIR, "ensemble_runner.py") : join(MATCHER_DIR, "job_fit_analyzer.py");
    const pipelineTag = isEnsemble ? "claude-ensemble" : "claude";
    await runCommand(PYTHON_BIN, [script, "--jobs-jsonl", matchRunInputPath(runId), "--results-jsonl",
      matchRunResultsPath(runId), "--profile-dir", join(MATCHER_DIR, CAREER_OPS_DIR), "--pipeline", pipelineTag],
      { env: process.env, logPrefix: `match-run ${runId}`, logFile: matchRunLogPath(runId), onLine: logLineHandler, onSpawn: (child) => activeRunProcesses.set(runId, child) });

    const results = await readJsonl(matchRunResultsPath(runId)) as Array<Record<string, unknown>>;
    const matchedCount = results.filter((row) => row.status === "ok").length;
    const failedCount = results.filter((row) => row.status === "error").length;
    if (results.length > 0 && matchedCount === 0 && failedCount === results.length) {
      const firstError = results[0]?.error as string | undefined;
      throw new Error(firstError ?? "All jobs failed in Python pipeline");
    }

    const scoreByJobKey = new Map<string, number>();
    for (const row of results) {
      if (row.status === "ok") {
        const key = `${row.provider}|${row.source_key}|${row.job_id}`;
        const score5 = (row.analysis as Record<string, unknown>)?.score_5 as number | undefined;
        if (score5 !== undefined) scoreByJobKey.set(key, score5);
      }
    }

    markDiscordRunning();
    await persistRunResults(runId, results, notifyDiscordForScore);
    markAllDone(scoreByJobKey);

    await writeManifest({ ...manifest, status: "completed", finished_at: new Date().toISOString(),
      matched_count: matchedCount, failed_count: results.length - matchedCount });
  } catch (err) {
    const errMsg = err instanceof Error ? err.message : String(err);
    console.error(`executeMatchRunFromInput ${runId} error:`, err);
    const nextAttempt = (queueItems[0]?.attempt ?? 0) + 1;
    const isPermanent = nextAttempt >= (queueItems[0]?.max_attempts ?? 3);
    markAllFailed(errMsg, isPermanent, nextAttempt);
    await writeManifest({ ...manifest, status: "failed", finished_at: new Date().toISOString(),
      error: errMsg });
  } finally {
    activeRunIds.delete(runId);
    activeRunProcesses.delete(runId);
  }
}

export async function executeMatchRun(runId: string, jobs: JobRow[], mode?: string): Promise<void> {
  const manifest = await readManifest(runId);
  if (manifest === null) {
    return;
  }

  activeRunIds.add(runId);

  const effectiveMode = mode ?? "claude";
  const now = new Date().toISOString();

  // One QueueItem per job so subtask state never mixes between different positions
  const queueItems: QueueItem[] = jobs.map((job) => ({
    id: `${runId}:${job.provider}|${job.source_key}|${job.job_id}`,
    job_key: `${job.provider}|${job.source_key}|${job.job_id}`,
    title: job.title ?? "Unknown job",
    company: companyName(job),
    mode: effectiveMode,
    status: "running" as QueueTaskStatus,
    subtasks: buildSubtasks(effectiveMode),
    attempt: 1,
    max_attempts: 3,
    created_at: now,
    updated_at: now,
  }));
  // Fallback for empty job list
  if (queueItems.length === 0) {
    queueItems.push({ id: runId, job_key: runId, title: "Unknown job", company: "", mode: effectiveMode, status: "running", subtasks: buildSubtasks(effectiveMode), attempt: 1, max_attempts: 3, created_at: now, updated_at: now });
  }
  await Promise.all(queueItems.map(upsertQueueItem));

  // Per-job log handlers, scoped by job label (Company | Title)
  const perJobHandlers = queueItems.map((qi, idx) => {
    const job = jobs[idx];
    const label = job ? `${companyName(job)} | ${job.title ?? job.job_id}` : qi.id;
    let current = qi;
    return makeLogLineHandler(current, label, (updated) => {
      current = updated;
      upsertQueueItem(updated).catch(() => {});
      // keep reference in sync for error handler below
      queueItems[idx] = updated;
    });
  });
  const logLineHandler = makeBatchLogLineHandler(perJobHandlers);

  const markAllDone = async (subtaskId: string, patch: Partial<QueueSubtask>): Promise<void> => {
    await Promise.all(queueItems.map((qi) =>
      upsertQueueItem({ ...qi, subtasks: qi.subtasks.map((s) => s.id === subtaskId ? { ...s, ...patch } : s), updated_at: new Date().toISOString() })
    ));
  };

  const markAllFinished = async (status: QueueTaskStatus, errMsg?: string, scoreByJobKey?: Map<string, number>): Promise<void> => {
    const nextAttempt = (queueItems[0]?.attempt ?? 1) + 1;
    const isPermanent = nextAttempt >= (queueItems[0]?.max_attempts ?? 3);
    await Promise.all(queueItems.map((qi) => {
      const score = status === "done" ? scoreByJobKey?.get(qi.job_key) : undefined;
      return upsertQueueItem({
        ...qi,
        attempt: nextAttempt,
        status: status === "done" ? "done" : (isPermanent ? "permanent_error" : "retrying"),
        next_retry_at: status !== "done" && !isPermanent ? new Date(Date.now() + 30 * 2 ** nextAttempt * 1000).toISOString() : undefined,
        error: errMsg,
        ...(score !== undefined ? { score } : {}),
        subtasks: status === "done" ? qi.subtasks : qi.subtasks.map((s) => s.status === "todo" || s.status === "running" ? { ...s, status: "error" as QueueTaskStatus } : s),
        updated_at: new Date().toISOString(),
      });
    }));
  };

  try {
    const runningManifest: MatchRunManifest = {
      ...manifest,
      status: "running",
      started_at: new Date().toISOString(),
    };
    await writeManifest(runningManifest);

    const preparedManifest = await writeBatchInput(runId, jobs, runningManifest);
    await writeManifest(preparedManifest);

    const isEnsemble = effectiveMode === "claude-ensemble";
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
        onLine: logLineHandler,
        onSpawn: (child) => activeRunProcesses.set(runId, child),
      }
    );

    const results = await readJsonl(matchRunResultsPath(runId)) as Array<Record<string, unknown>>;
    const matchedCount = results.filter((row) => row.status === "ok").length;
    const failedCount = results.length - matchedCount;
    if (results.length > 0 && matchedCount === 0 && failedCount === results.length) {
      const firstError = results[0]?.error as string | undefined;
      throw new Error(firstError ?? "All jobs failed in Python pipeline");
    }

    const scoreByJobKey = new Map<string, number>();
    for (const row of results) {
      if (row.status === "ok") {
        const key = `${row.provider}|${row.source_key}|${row.job_id}`;
        const score5 = (row.analysis as Record<string, unknown>)?.score_5 as number | undefined;
        if (score5 !== undefined) scoreByJobKey.set(key, score5);
      }
    }

    await markAllDone("discord", { status: "running", started_at: new Date().toISOString() });
    await persistRunResults(runId, results, notifyDiscordForScore);
    await markAllFinished("done", undefined, scoreByJobKey);

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
    const errMsg = error instanceof Error ? error.message : String(error);
    await markAllFinished("error", errMsg);
    await writeManifest({
      ...manifest,
      status: "failed",
      finished_at: new Date().toISOString(),
      error: errMsg,
      result_file: matchRunResultsPath(runId),
      log_file: matchRunLogPath(runId),
    });
  } finally {
    activeRunIds.delete(runId);
    activeRunProcesses.delete(runId);
  }
}

/** Extract the run ID from a composite queue item ID (`${runId}:${jobKey}`). */
export function runIdFromItemId(itemId: string): string {
  const colonIdx = itemId.indexOf(":");
  return colonIdx === -1 ? itemId : itemId.slice(0, colonIdx);
}

export function killRun(runId: string): boolean {
  const child = activeRunProcesses.get(runId);
  if (!child) return false;
  child.kill("SIGTERM");
  activeRunProcesses.delete(runId);
  return true;
}

// --- Queue helpers ---

const ENSEMBLE_SCORER_LABELS: Record<string, string> = {
  "llama-4-maverick-17b-128e-instruct": "Maverick scorer",
  "kimi-k2-instruct": "Kimi-K2 scorer",
  "llama-3.3-nemotron-super-49b-v1.5": "Nemotron scorer",
};

function shortModelName(fullId: string): string {
  return fullId.split("/").pop() ?? fullId;
}

function buildSubtasks(mode: string): QueueSubtask[] {
  if (mode === "claude-ensemble") {
    const scorerEnv = process.env.NVIDIA_ENSEMBLE_SCORERS || "meta/llama-4-maverick-17b-128e-instruct,moonshotai/kimi-k2-instruct,nvidia/llama-3.3-nemotron-super-49b-v1.5";
    const synthEnv = process.env.NVIDIA_ENSEMBLE_SYNTHESIZER || "nvidia/llama-3.3-nemotron-super-49b-v1.5";
    const scorerIds = ["scorer:maverick", "scorer:kimi", "scorer:nemotron"];
    const scorerSubtasks = scorerEnv.split(",").map((m, i) => ({
      id: scorerIds[i] ?? `scorer:${i}`,
      label: `${shortModelName(m.trim())} (scorer)`,
      status: "todo" as QueueTaskStatus,
    }));
    return [
      ...scorerSubtasks,
      { id: "synthesis", label: `${shortModelName(synthEnv)} (synthesis)`, status: "todo" },
      { id: "discord", label: "Discord push", status: "todo" },
    ];
  }
  const singleModel = process.env.NVIDIA_MODEL ?? "llama-4-maverick-17b-128e-instruct";
  return [
    { id: "model:claude", label: `${shortModelName(singleModel)} (scorer)`, status: "todo" },
    { id: "discord", label: "Discord push", status: "todo" },
  ];
}

function scorerSubtaskId(modelName: string): string | null {
  if (modelName.includes("maverick")) return "scorer:maverick";
  if (modelName.includes("kimi")) return "scorer:kimi";
  if (modelName.includes("nemotron")) return "scorer:nemotron";
  return null;
}

// jobLabel matches the Python log format: "Company | Title"
function makeLogLineHandler(
  item: QueueItem,
  jobLabel: string,
  onUpdate: (updated: QueueItem) => void,
): (line: string) => void {
  let current = item;
  // Escape the label for use in a regex
  const labelPattern = jobLabel.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const forThisJob = new RegExp(`\\[ensemble(?:-batch)?\\]\\s+(?:#\\d+\\s+)?${labelPattern}\\s+\\|`, "i");

  const update = (patch: Partial<QueueItem>, subtaskId?: string, subtaskPatch?: Partial<QueueSubtask>): void => {
    const subtasks = subtaskId
      ? current.subtasks.map((s) => s.id === subtaskId ? { ...s, ...subtaskPatch } : s)
      : current.subtasks;
    current = { ...current, ...patch, subtasks, updated_at: new Date().toISOString() };
    onUpdate(current);
  };

  return (line: string): void => {
    // Only handle log lines that belong to this job
    if (!forThisJob.test(line)) return;

    // job start — mark all scorer subtasks running
    if (/\|\s*start\b/i.test(line)) {
      const now = new Date().toISOString();
      update({ status: "running" as QueueTaskStatus }, undefined, undefined);
      current = {
        ...current,
        status: "running" as QueueTaskStatus,
        subtasks: current.subtasks.map((s) =>
          s.id.startsWith("scorer:") || s.id === "model:claude"
            ? { ...s, status: "running" as QueueTaskStatus, started_at: now }
            : s,
        ),
        updated_at: now,
      };
      onUpdate(current);
      return;
    }

    // scorer done
    const scorerDone = line.match(/\|\s*scorer\s+([\w\-./]+)\s*\|\s*avg=/i);
    if (scorerDone) {
      const id = scorerSubtaskId(scorerDone[1]);
      if (id) update({}, id, { status: "done", finished_at: new Date().toISOString() });
      return;
    }
    // scorer error
    const scorerErr = line.match(/\|\s*scorer\s+([\w\-./]+)\s*\|\s*error[:\s]/i);
    if (scorerErr) {
      const id = scorerSubtaskId(scorerErr[1]);
      if (id) update({}, id, { status: "error", finished_at: new Date().toISOString() });
      return;
    }
    // synthesizing
    if (/\|\s*synthesizing/i.test(line)) {
      update({}, "synthesis", { status: "running", started_at: new Date().toISOString() });
      return;
    }
    // synthesis done
    if (/\|\s*synthesis done/i.test(line)) {
      update({}, "synthesis", { status: "done", finished_at: new Date().toISOString() });
      return;
    }
  };
}

// Aggregates multiple per-job handlers into one onLine callback
function makeBatchLogLineHandler(handlers: Array<(line: string) => void>): (line: string) => void {
  return (line: string): void => { for (const h of handlers) h(line); };
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

  // Also reset any queue items stuck in running/todo/retrying state — they belong
  // to processes that died with the previous server instance.
  try {
    const items = await readQueue();
    const orphaned = items.filter((i) => i.status === "running" || i.status === "todo");
    await Promise.all(orphaned.map((i) => upsertQueueItem({
      ...i,
      status: "permanent_error",
      error: "orphaned: server restarted",
      subtasks: i.subtasks.map((s) =>
        s.status === "running" || s.status === "todo" ? { ...s, status: "error" as QueueTaskStatus, error: "orphaned" } : s,
      ),
      updated_at: new Date().toISOString(),
    })));
  } catch { /* queue file may not exist yet */ }
}

