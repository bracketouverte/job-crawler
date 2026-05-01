#!/usr/bin/env node
import { unlink } from "node:fs/promises";
import { runCrawler } from "./runner.js";
import { parseProviderList } from "./source-loader.js";
import type { Provider } from "./types.js";

type CliOptions = {
  sources: string;
  providers: string;
  concurrency: number;
  out: string;
  report: string;
  catalogDbFile: string;
  catalogFile?: string;
  excludeSources?: string;
  sample?: number;
  maxJobsPerSource?: number;
  maxAgeHours?: number;
  progressEveryMs: number;
  providerConcurrency: Partial<Record<Provider, number>>;
  timeoutMs: number;
  retries: number;
  progressFile: string;
};

const defaults: CliOptions = {
  sources: "/data/sources",
  providers: "all",
  concurrency: 50,
  out: "/app/output/jobs.jsonl",
  report: "/app/output/report.json",
  catalogDbFile: "/app/state/catalog.sqlite",
  progressEveryMs: 10000,
  providerConcurrency: { ashby: 2 },
  timeoutMs: 15000,
  retries: 2,
  progressFile: "/app/state/crawler-progress.json",
};

async function main(): Promise<void> {
  const options = parseArgs(process.argv.slice(2));
  const selectedProviders = parseProviderList(options.providers);

  const report = await runCrawler({
    sourcesDir: options.sources,
    selectedProviders,
    concurrency: options.concurrency,
    outFile: options.out,
    reportFile: options.report,
    catalogDbFile: options.catalogDbFile,
    catalogFile: options.catalogFile,
    excludeSourcesFile: options.excludeSources,
    sample: options.sample,
    maxJobsPerSource: options.maxJobsPerSource,
    maxAgeHours: options.maxAgeHours,
    progressEveryMs: options.progressEveryMs,
    providerConcurrency: options.providerConcurrency,
    timeoutMs: options.timeoutMs,
    retries: options.retries,
    progressFile: options.progressFile,
  });

  await unlink(options.progressFile).catch(() => undefined);

  console.log(JSON.stringify({
    started_at: report.started_at,
    ended_at: report.ended_at,
    total_jobs: report.total_jobs,
    failures: report.failures.length,
    out: options.out,
    report: options.report
  }, null, 2));
}

export function parseArgs(args: string[]): CliOptions {
  const options: CliOptions = { ...defaults };

  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === undefined) {
      continue;
    }

    if (arg === "--help" || arg === "-h") {
      printHelp();
      process.exit(0);
    }

    const next = args[index + 1];
    switch (arg) {
      case "--sources":
        options.sources = requireValue(arg, next);
        index += 1;
        break;
      case "--providers":
        options.providers = requireValue(arg, next);
        index += 1;
        break;
      case "--concurrency":
        options.concurrency = parsePositiveInteger(arg, requireValue(arg, next));
        index += 1;
        break;
      case "--out":
        options.out = requireValue(arg, next);
        index += 1;
        break;
      case "--report":
        options.report = requireValue(arg, next);
        index += 1;
        break;
      case "--catalog-db":
        options.catalogDbFile = requireValue(arg, next);
        index += 1;
        break;
      case "--catalog-file":
        options.catalogFile = requireValue(arg, next);
        index += 1;
        break;
      case "--exclude-sources":
        options.excludeSources = requireValue(arg, next);
        index += 1;
        break;
      case "--sample":
        options.sample = parsePositiveInteger(arg, requireValue(arg, next));
        index += 1;
        break;
      case "--max-jobs-per-source":
        options.maxJobsPerSource = parsePositiveInteger(arg, requireValue(arg, next));
        index += 1;
        break;
      case "--max-age-hours":
        options.maxAgeHours = parsePositiveInteger(arg, requireValue(arg, next));
        index += 1;
        break;
      case "--progress-every-ms":
        options.progressEveryMs = parseNonNegativeInteger(arg, requireValue(arg, next));
        index += 1;
        break;
      case "--provider-concurrency":
        options.providerConcurrency = parseProviderConcurrency(requireValue(arg, next));
        index += 1;
        break;
      case "--timeout-ms":
        options.timeoutMs = parsePositiveInteger(arg, requireValue(arg, next));
        index += 1;
        break;
      case "--retries":
        options.retries = parseNonNegativeInteger(arg, requireValue(arg, next));
        index += 1;
        break;
      case "--progress-file":
        options.progressFile = requireValue(arg, next);
        index += 1;
        break;
      default:
        throw new Error(`Unknown argument: ${arg}`);
    }
  }

  return options;
}

function requireValue(flag: string, value: string | undefined): string {
  if (value === undefined || value.startsWith("--")) {
    throw new Error(`${flag} requires a value`);
  }
  return value;
}

function parsePositiveInteger(flag: string, value: string): number {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${flag} must be a positive integer`);
  }
  return parsed;
}

function parseNonNegativeInteger(flag: string, value: string): number {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 0) {
    throw new Error(`${flag} must be a non-negative integer`);
  }
  return parsed;
}

function printHelp(): void {
  console.log(`Usage: crawl [options]

Options:
  --sources <dir>          Source JSON directory (default: /data/sources)
  --providers <list|all>   Providers to crawl (default: all)
  --concurrency <n>        Global source concurrency (default: 50)
  --out <file>             JSONL output path (default: /app/output/jobs.jsonl)
  --report <file>          Report JSON path (default: /app/output/report.json)
  --catalog-db <file>      SQLite catalog state file (default: /app/state/catalog.sqlite)
  --catalog-file <file>    Persistent current-jobs catalog JSONL (add/update/remove)
  --exclude-sources <file> JSONL source quarantine file
  --sample <n>             Crawl only first n sources per provider
  --max-jobs-per-source <n> Emit at most n jobs per source
  --max-age-hours <n>      Keep only jobs where updated_at is within last n hours
  --progress-every-ms <n>  Progress log interval, 0 disables it (default: 10000)
  --provider-concurrency <spec> Per-provider limits, e.g. ashby=2,workday=10 (default: ashby=2)
  --timeout-ms <n>         Per-request timeout (default: 15000)
  --retries <n>            Transient retry count (default: 2)
`);
}

function parseProviderConcurrency(value: string): Partial<Record<Provider, number>> {
  if (value.trim() === "") {
    throw new Error("--provider-concurrency must not be empty");
  }

  const limits: Partial<Record<Provider, number>> = {};
  for (const entry of value.split(",")) {
    const [provider, limit] = entry.split("=");
    if (provider === undefined || limit === undefined) {
      throw new Error(`Invalid provider concurrency entry "${entry}". Expected provider=limit`);
    }

    const parsedProvider = parseProviderList(provider)[0];
    if (parsedProvider === undefined) {
      throw new Error(`Invalid provider concurrency entry "${entry}". Expected provider=limit`);
    }
    limits[parsedProvider] = parsePositiveInteger(`--provider-concurrency ${provider}`, limit);
  }

  return limits;
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
