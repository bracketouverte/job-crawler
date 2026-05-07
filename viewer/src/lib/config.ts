import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import type { CartJobPayload } from "./types.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

export const DB_PATH = process.env.CATALOG_DB ?? "/app/state/catalog.sqlite";
export const STATE_DIR = process.env.STATE_DIR ?? dirname(DB_PATH);
export const MATCH_RUNS_DIR = process.env.MATCH_RUNS_DIR ?? join(STATE_DIR, "match-runs");
export const ANALYSIS_CACHE_PATH = process.env.ANALYSIS_CACHE_PATH ?? join(STATE_DIR, "job-analysis-cache.json");
export const HIDDEN_JOBS_PATH = process.env.HIDDEN_JOBS_PATH ?? join(STATE_DIR, "hidden-jobs.json");
export const SCORE_NOTIFICATIONS_PATH = process.env.SCORE_NOTIFICATIONS_PATH ?? join(STATE_DIR, "score-notifications.json");
export const MATCHER_DIR = process.env.MATCHER_DIR ?? "/matcher";
export const PYTHON_BIN = process.env.PYTHON_BIN ?? "python3";
export const CAREER_OPS_DIR = process.env.CAREER_OPS_DIR?.trim() ?? "career-ops";
export const LOGO_DEV_PUBLISHABLE_KEY = process.env.LOGO_DEV_PUBLISHABLE_KEY?.trim() ?? "";
export const LOGO_DEV_SECRET_KEY = process.env.LOGO_DEV_SECRET_KEY?.trim() ?? "";
export const PORT = parseInt(process.env.PORT ?? "3000", 10);
export const SAVED_SEARCH_ANALYZER_ENABLED = process.env.SAVED_SEARCH_ANALYZER_ENABLED !== "0";
export const SAVED_SEARCH_ANALYZER_INTERVAL_MS = parseInt(process.env.SAVED_SEARCH_ANALYZER_INTERVAL_MS ?? "60000", 10);
export const SAVED_SEARCHES_PATH = process.env.SAVED_SEARCHES_PATH ?? join(__dirname, "../../public/saved-searches.json");
export const CRAWLER_ACTIVE_LOCK_PATH = process.env.CRAWLER_ACTIVE_LOCK_PATH ?? join(STATE_DIR, "crawler-active.lock");
export const CRAWLER_ACTIVE_LOCK_STALE_MS = parseInt(process.env.CRAWLER_ACTIVE_LOCK_STALE_MS ?? "7200000", 10);
export const CRAWLER_PROGRESS_PATH = process.env.CRAWLER_PROGRESS_PATH ?? join(STATE_DIR, "crawler-progress.json");
export const DISCORD_WEBHOOK_URL = process.env.DISCORD_WEBHOOK_URL?.trim() ?? "";
export const SCORE_NOTIFY_MIN_SCORE = parseFloat(process.env.SCORE_NOTIFY_MIN_SCORE ?? "4");

export const LOGO_CACHE_MAX = 2000;

// Global mutable state
export const logoDevBrandCache = new Map<string, string | null>();
export const activeRunIds = new Set<string>();
export let savedSearchAnalyzerBusy = false;
export let savedSearchAnalyzerPaused = false;
export let savedSearchAnalyzerCurrent: {
  runId: string;
  jobKey: string;
  searchId: string | null;
  searchLabel: string | null;
  job: CartJobPayload;
  startedAt: string;
} | null = null;

export function setSavedSearchAnalyzerBusy(value: boolean): void {
  savedSearchAnalyzerBusy = value;
}

export function setSavedSearchAnalyzerPaused(value: boolean): void {
  savedSearchAnalyzerPaused = value;
}

export function setSavedSearchAnalyzerCurrent(
  value: {
    runId: string;
    jobKey: string;
    searchId: string | null;
    searchLabel: string | null;
    job: CartJobPayload;
    startedAt: string;
  } | null,
): void {
  savedSearchAnalyzerCurrent = value;
}
