import { createWriteStream } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { CatalogStore } from "./catalog-store.js";
import { HttpError, createHttpClient } from "./http.js";
import { crawlerByProvider } from "./providers/index.js";
import { isProvider, loadSourceFile, sourceKey } from "./source-loader.js";
import { CrawlFailure, CrawlReport, NormalizedJob, Provider, ProviderStats, providers, SourceEntry } from "./types.js";

export type RunOptions = {
  sourcesDir: string;
  selectedProviders: Provider[];
  concurrency: number;
  outFile: string;
  reportFile: string;
  catalogDbFile?: string;
  catalogFile?: string;
  excludeSourcesFile?: string;
  sample?: number;
  maxJobsPerSource?: number;
  maxAgeHours?: number;
  progressEveryMs: number;
  providerConcurrency: Partial<Record<Provider, number>>;
  timeoutMs: number;
  retries: number;
  progressFile?: string;
};

type WorkItem = {
  provider: Provider;
  source: SourceEntry;
};

export async function runCrawler(options: RunOptions): Promise<CrawlReport> {
  const startedAt = new Date().toISOString();
  const stats = initStats();
  const failures: CrawlFailure[] = [];
  const itemsByProvider = new Map<Provider, WorkItem[]>();
  const excludedSources = await loadExcludedSources(options.excludeSourcesFile);

  for (const provider of options.selectedProviders) {
    const sourceFile = await loadSourceFile(options.sourcesDir, provider);
    const companies = options.sample === undefined ? sourceFile.companies : sourceFile.companies.slice(0, options.sample);
    stats[provider].sources = companies.length;
    const providerItems: WorkItem[] = [];
    for (const source of companies) {
      const key = sourceKey(provider, source);
      if (excludedSources.has(exclusionKey(provider, key))) {
        stats[provider].skipped += 1;
        continue;
      }
      providerItems.push({ provider, source });
    }
    itemsByProvider.set(provider, providerItems);
  }

  const items = interleaveWorkItems(options.selectedProviders, itemsByProvider);

  await mkdir(dirname(options.outFile), { recursive: true });
  await mkdir(dirname(options.reportFile), { recursive: true });

  const catalogStore = options.catalogDbFile === undefined ? undefined : new CatalogStore(options.catalogDbFile);

  const output = createWriteStream(options.outFile, { encoding: "utf8" });
  const writer = new JsonlWriter(output);
  const seenJobs = new Set<string>();
  const http = createHttpClient({ timeoutMs: options.timeoutMs, retries: options.retries });

  let cursor = 0;
  let completed = 0;
  const workerCount = Math.min(Math.max(options.concurrency, 1), items.length || 1);
  const providerLimiters = createProviderLimiters(options.providerConcurrency);
  const minUpdatedAtMs = options.maxAgeHours === undefined
    ? undefined
    : Date.now() - options.maxAgeHours * 60 * 60 * 1000;
  const startedMs = Date.now();
  const progressTimer = options.progressEveryMs > 0
    ? setInterval(() => logProgress("progress", startedMs, completed, items.length, stats, failures.length, options.progressFile), options.progressEveryMs)
    : undefined;

  logProgress("start", startedMs, completed, items.length, stats, failures.length, options.progressFile);

  async function worker(): Promise<void> {
    while (true) {
      const item = items[cursor];
      cursor += 1;
      if (item === undefined) {
        return;
      }

      const key = sourceKey(item.provider, item.source);
      const crawler = crawlerByProvider.get(item.provider);
      if (crawler === undefined) {
        recordFailure(failures, stats[item.provider], item.provider, key, new Error(`No crawler for provider ${item.provider}`));
        continue;
      }

      try {
        const jobs = await providerLimiters[item.provider].run(async () => {
          const fetchedAt = new Date().toISOString();
          return crawler.crawl(item.source, {
            http,
            fetchedAt: () => fetchedAt,
            maxJobsPerSource: options.maxJobsPerSource
          });
        });
        if (catalogStore !== undefined) {
          catalogStore.recordJobs(jobs, startedAt);
        }

        let emitted = 0;
        for (const job of jobs) {
          if (minUpdatedAtMs !== undefined && !isFreshEnough(job.posted_at ?? job.updated_at, minUpdatedAtMs)) {
            continue;
          }
          const dedupeKey = `${job.provider}:${job.source_key}:${job.job_id}`;
          if (seenJobs.has(dedupeKey)) {
            continue;
          }
          seenJobs.add(dedupeKey);
          await writer.write(job);
          emitted += 1;
        }

        stats[item.provider].succeeded += 1;
        stats[item.provider].jobs += emitted;
      } catch (error) {
        recordFailure(failures, stats[item.provider], item.provider, key, error);
      } finally {
        completed += 1;
      }
    }
  }

  try {
    await Promise.all(Array.from({ length: workerCount }, () => worker()));

    if (catalogStore !== undefined) {
      catalogStore.finalizeRun(startedAt);
      if (options.catalogFile !== undefined) {
        await catalogStore.exportJsonl(options.catalogFile);
      }
    }
  } finally {
    if (progressTimer !== undefined) {
      clearInterval(progressTimer);
    }
    await writer.close();
    catalogStore?.close();
  }

  const endedAt = new Date().toISOString();
  const report: CrawlReport = {
    started_at: startedAt,
    ended_at: endedAt,
    source_counts: Object.fromEntries(providers.map((provider) => [provider, stats[provider].sources])) as Record<Provider, number>,
    skipped_sources: providers.reduce((sum, provider) => sum + stats[provider].skipped, 0),
    skipped_by_provider: Object.fromEntries(providers.map((provider) => [provider, stats[provider].skipped])) as Record<Provider, number>,
    providers: stats,
    total_jobs: providers.reduce((sum, provider) => sum + stats[provider].jobs, 0),
    failures
  };

  await writeFile(options.reportFile, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  logProgress("done", startedMs, completed, items.length, stats, failures.length, options.progressFile);
  return report;
}

function initStats(): Record<Provider, ProviderStats> {
  return Object.fromEntries(
    providers.map((provider) => [
      provider,
      {
        sources: 0,
        skipped: 0,
        succeeded: 0,
        failed: 0,
        jobs: 0
      }
    ])
  ) as Record<Provider, ProviderStats>;
}

function recordFailure(
  failures: CrawlFailure[],
  stats: ProviderStats,
  provider: Provider,
  key: string,
  error: unknown
): void {
  const message = error instanceof Error ? error.message : String(error);
  const status = error instanceof HttpError ? error.status : undefined;
  console.error(JSON.stringify({ event: "failure", provider, source_key: key, status, message }));
  stats.failed += 1;
  failures.push({ provider, source_key: key, status, message });
}

export function writeJobForTest(job: NormalizedJob): string {
  return `${JSON.stringify(job)}\n`;
}

class JsonlWriter {
  private tail = Promise.resolve();

  constructor(private readonly stream: NodeJS.WritableStream) {}

  async write(job: NormalizedJob): Promise<void> {
    const next = this.tail.then(() => this.writeLine(job));
    this.tail = next.catch(() => undefined);
    return next;
  }

  async close(): Promise<void> {
    await this.tail;
    await new Promise<void>((resolve, reject) => {
      const onError = (error: Error): void => {
        this.stream.off("finish", onFinish);
        reject(error);
      };
      const onFinish = (): void => {
        this.stream.off("error", onError);
        resolve();
      };

      this.stream.once("error", onError);
      this.stream.once("finish", onFinish);
      this.stream.end();
    });
  }

  private writeLine(job: NormalizedJob): Promise<void> {
    const line = `${JSON.stringify(job)}\n`;
    return new Promise((resolve, reject) => {
      const onError = (error: Error): void => {
        this.stream.off("drain", onDrain);
        reject(error);
      };
      const onDrain = (): void => {
        this.stream.off("error", onError);
        resolve();
      };

      this.stream.once("error", onError);
      if (this.stream.write(line)) {
        this.stream.off("error", onError);
        resolve();
        return;
      }
      this.stream.once("drain", onDrain);
    });
  }
}

async function loadExcludedSources(file: string | undefined): Promise<Set<string>> {
  if (file === undefined) {
    return new Set();
  }

  const raw = await readFile(file, "utf8");
  const excluded = new Set<string>();
  const lines = raw.split(/\r?\n/);

  for (const [index, line] of lines.entries()) {
    if (line.trim() === "") {
      continue;
    }

    let parsed: unknown;
    try {
      parsed = JSON.parse(line);
    } catch (error) {
      throw new Error(`${file}:${index + 1} is not valid JSON: ${error instanceof Error ? error.message : String(error)}`);
    }

    if (!parsed || typeof parsed !== "object") {
      throw new Error(`${file}:${index + 1} must be a JSON object`);
    }

    const row = parsed as Record<string, unknown>;
    const provider = row.provider ?? row.ats;
    const sourceKeyValue = row.source_key ?? row.identifier;

    if (typeof provider !== "string" || !isProvider(provider)) {
      throw new Error(`${file}:${index + 1} has unsupported provider "${String(provider)}"`);
    }
    if (typeof sourceKeyValue !== "string" || sourceKeyValue === "") {
      throw new Error(`${file}:${index + 1} must contain a non-empty source_key`);
    }

    excluded.add(exclusionKey(provider, sourceKeyValue));
  }

  return excluded;
}

function exclusionKey(provider: Provider, key: string): string {
  return `${provider}:${key}`;
}

function isFreshEnough(updatedAt: string | null, minUpdatedAtMs: number): boolean {
  if (updatedAt === null) {
    return false;
  }

  const updatedAtMs = Date.parse(updatedAt);
  if (Number.isNaN(updatedAtMs)) {
    return false;
  }

  return updatedAtMs >= minUpdatedAtMs;
}

class Limiter {
  private active = 0;
  private readonly queue: Array<() => void> = [];

  constructor(private readonly limit: number) {}

  async run<T>(task: () => Promise<T>): Promise<T> {
    await this.acquire();
    try {
      return await task();
    } finally {
      this.release();
    }
  }

  private acquire(): Promise<void> {
    if (this.active < this.limit) {
      this.active += 1;
      return Promise.resolve();
    }

    return new Promise((resolve) => {
      this.queue.push(() => {
        this.active += 1;
        resolve();
      });
    });
  }

  private release(): void {
    this.active -= 1;
    const next = this.queue.shift();
    if (next !== undefined) {
      next();
    }
  }
}

function createProviderLimiters(limits: Partial<Record<Provider, number>>): Record<Provider, Limiter> {
  return Object.fromEntries(
    providers.map((provider) => [provider, new Limiter(limits[provider] ?? Number.MAX_SAFE_INTEGER)])
  ) as Record<Provider, Limiter>;
}

function interleaveWorkItems(selectedProviders: Provider[], itemsByProvider: Map<Provider, WorkItem[]>): WorkItem[] {
  const providerQueues = selectedProviders.map((provider) => ({
    provider,
    items: itemsByProvider.get(provider) ?? [],
    index: 0
  }));
  const items: WorkItem[] = [];

  while (true) {
    let addedAny = false;
    for (const queue of providerQueues) {
      const item = queue.items[queue.index];
      if (item === undefined) {
        continue;
      }
      items.push(item);
      queue.index += 1;
      addedAny = true;
    }

    if (!addedAny) {
      return items;
    }
  }
}

function logProgress(
  event: "start" | "progress" | "done",
  startedMs: number,
  completed: number,
  total: number,
  stats: Record<Provider, ProviderStats>,
  failureCount: number,
  progressFile?: string
): void {
  const elapsedSeconds = Math.round((Date.now() - startedMs) / 1000);
  const percent = total === 0 ? 100 : Math.round((completed / total) * 100);
  let jobs = 0;
  let succeeded = 0;
  let failed = 0;
  const byProvider = Object.fromEntries(
    providers.map((provider) => {
      const s = stats[provider];
      jobs += s.jobs;
      succeeded += s.succeeded;
      failed += s.failed;
      return [provider, { done: s.succeeded + s.failed, total: s.sources, skipped: s.skipped, jobs: s.jobs, failed: s.failed }];
    })
  );

  const payload = {
    event,
    elapsed_seconds: elapsedSeconds,
    completed_sources: completed,
    total_sources: total,
    percent,
    succeeded_sources: succeeded,
    failed_sources: failed,
    total_jobs: jobs,
    failures_recorded: failureCount,
    by_provider: byProvider
  };

  console.log(JSON.stringify(payload));

  if (progressFile) {
    writeFile(progressFile, `${JSON.stringify(payload)}\n`, "utf8").catch(() => undefined);
  }
}
