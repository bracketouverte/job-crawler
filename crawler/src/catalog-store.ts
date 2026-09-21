import { createWriteStream } from "node:fs";
import { mkdir, rename } from "node:fs/promises";
import { dirname } from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import pg from "pg";
import { NormalizedJob } from "./types.js";

// Lazy import better-sqlite3 so pg-only env still works if module missing
import { createRequire } from "node:module";
let BetterSqlite3: any = null;
try {
  const require = createRequire(import.meta.url);
  BetterSqlite3 = require("better-sqlite3");
} catch {
  // sqlite not available – postgres-only mode
}

type CatalogRow = {
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
  office: string | null;
  language: string | null;
  updated_at: string | null;
  posted_at: string | null;
  job_url: string | null;
  fetched_at: string;
  first_seen_at: string;
  last_seen_at: string;
  seen_run_id: string;
};

type CatalogExportRow = Omit<CatalogRow, "seen_run_id">;

function isPostgresConnectionString(s: string): boolean {
  return s.startsWith("postgres://") || s.startsWith("postgresql://");
}

function shouldUsePostgres(explicit?: string): boolean {
  const driver = (process.env.CATALOG_DRIVER || "auto").toLowerCase();
  if (driver === "sqlite") return false;
  if (driver === "postgres") return true;
  // auto
  if (explicit && isPostgresConnectionString(explicit)) return true;
  if (process.env.DATABASE_URL) return true;
  if (process.env.PG_HOST) return true;
  return false;
}

function toTimestampOrNull(val: unknown): string | null {
  if (val === null || val === undefined) return null;
  const s = String(val).trim();
  if (!s) return null;
  // Common non-ISO placeholder from scrapers – treat as null
  if (/^posted\b/i.test(s)) return null;
  // Try ISO parse; reject obvious non-dates like "Posted Today", "Just posted", etc.
  const ms = Date.parse(s);
  if (Number.isNaN(ms)) return null;
  // Reject year < 2000 or > 2100 as likely garbage
  const d = new Date(s);
  const year = d.getUTCFullYear();
  if (year < 2000 || year > 2100) return null;
  return d.toISOString();
}

function createPgPool(explicit?: string): pg.Pool {
  if (explicit && isPostgresConnectionString(explicit)) {
    return new pg.Pool({ connectionString: explicit, max: 20, idleTimeoutMillis: 30000, connectionTimeoutMillis: 5000 });
  }
  if (process.env.DATABASE_URL) {
    return new pg.Pool({ connectionString: process.env.DATABASE_URL, max: 20, idleTimeoutMillis: 30000, connectionTimeoutMillis: 5000 });
  }
  return new pg.Pool({
    host: process.env.PG_HOST || "localhost",
    port: parseInt(process.env.PG_PORT || "5432"),
    database: process.env.PG_DB || "job_catalog",
    user: process.env.PG_USER || "job_admin",
    password: process.env.PG_PASSWORD || "job_admin_password",
    max: 20,
    idleTimeoutMillis: 30000,
    connectionTimeoutMillis: 5000,
  });
}

/**
 * CatalogStore with Postgres primary + SQLite fallback/backup.
 * - CATALOG_DRIVER=postgres -> only postgres
 * - CATALOG_DRIVER=sqlite   -> only sqlite (path required)
 * - CATALOG_DRIVER=auto     -> use postgres if PG_HOST/DATABASE_URL set, fallback to sqlite; when both available, dual-write.
 */
export class CatalogStore {
  private readonly pgPool?: pg.Pool;
  private readonly sqlitePath?: string;
  private sqliteDb: any = null;
  private sqliteUpsert: any = null;
  private sqliteInsertMany: any = null;
  private sqliteDeleteMissing: any = null;
  private sqliteSelectAll: any = null;
  private initialized = false;
  private usePg: boolean;
  private useSqlite: boolean;
  private pgInitialized = false;
  private sqliteQueue: Promise<void> = Promise.resolve();

  constructor(dbPath?: string) {
    // dbPath is the sqlite file path from CLI --catalog-db (e.g. /app/state/catalog.sqlite)
    // If it looks like a postgres URL, treat it as explicit pg connection string.
    if (dbPath && isPostgresConnectionString(dbPath)) {
      this.usePg = true;
      this.useSqlite = false;
      this.pgPool = createPgPool(dbPath);
      this.sqlitePath = undefined;
      return;
    }

    this.usePg = shouldUsePostgres(dbPath);
    // Use sqlite if we have a file path and (not postgres-only or we want backup)
    // In auto+pg mode we dual-write to sqlite for backup.
    if (dbPath) {
      this.sqlitePath = dbPath;
      // If driver=postgres we don't use sqlite even if path given
      const driver = (process.env.CATALOG_DRIVER || "auto").toLowerCase();
      this.useSqlite = driver !== "postgres";
      // In auto+pg we keep both (dual write)
      if (this.usePg && this.useSqlite) {
        // dual mode – pg primary, sqlite backup
      }
    } else {
      this.sqlitePath = undefined;
      this.useSqlite = false;
      // pg-only without file path is allowed (e.g. no --catalog-db)
      if (!this.usePg) {
        // No store configured – runner will treat as undefined, but we allow empty
        this.usePg = false;
        this.useSqlite = false;
      }
    }

    if (this.usePg) {
      this.pgPool = createPgPool();
    }

    if (this.useSqlite) {
      if (!BetterSqlite3) {
        console.warn("[CatalogStore] better-sqlite3 not available, sqlite disabled");
        this.useSqlite = false;
      } else if (!this.sqlitePath) {
        console.warn("[CatalogStore] sqlite path not provided, sqlite disabled");
        this.useSqlite = false;
      }
    }
  }

  private ensureSqlite(): void {
    if (!this.useSqlite || this.sqliteDb) return;
    const path = this.sqlitePath!;
    this.sqliteDb = new BetterSqlite3(path);
    this.sqliteDb.pragma("busy_timeout = 30000");
    this.sqliteDb.pragma("journal_mode = WAL");
    this.sqliteDb.pragma("synchronous = NORMAL");
    this.sqliteDb.pragma("foreign_keys = ON");
    this.sqliteDb.exec(`
      CREATE TABLE IF NOT EXISTS catalog_jobs (
        provider TEXT NOT NULL,
        source_key TEXT NOT NULL,
        job_id TEXT NOT NULL,
        title TEXT,
        location TEXT,
        employment_type TEXT,
        compensation TEXT,
        department TEXT,
        office TEXT,
        language TEXT,
        updated_at TEXT,
        posted_at TEXT,
        job_url TEXT,
        fetched_at TEXT NOT NULL,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        seen_run_id TEXT NOT NULL,
        raw_json TEXT NOT NULL DEFAULT 'null',
        salary_min INTEGER,
        salary_max INTEGER,
        salary_currency TEXT,
        salary_period TEXT,
        salary_location TEXT,
        salary_is_estimated INTEGER DEFAULT 0,
        PRIMARY KEY (provider, source_key, job_id)
      );
      CREATE INDEX IF NOT EXISTS catalog_jobs_seen_run_id_idx ON catalog_jobs(seen_run_id);
      CREATE INDEX IF NOT EXISTS catalog_jobs_last_seen_at_idx ON catalog_jobs(last_seen_at);
      DROP INDEX IF EXISTS catalog_jobs_title_lower_idx;
      DROP INDEX IF EXISTS catalog_jobs_location_lower_idx;
    `);
    this.ensureSqliteColumn("catalog_jobs", "salary_currency", "TEXT");
    this.ensureSqliteColumn("catalog_jobs", "salary_period", "TEXT");
    this.ensureSqliteColumn("catalog_jobs", "salary_location", "TEXT");
    this.ensureSqliteColumn("catalog_jobs", "salary_is_estimated", "INTEGER DEFAULT 0");
    this.ensureSqliteColumn("catalog_jobs", "posted_at", "TEXT");
    this.ensureSqliteColumn("catalog_jobs", "salary_min", "INTEGER");
    this.ensureSqliteColumn("catalog_jobs", "salary_max", "INTEGER");

    this.sqliteUpsert = this.sqliteDb.prepare(`
      INSERT INTO catalog_jobs (
        provider, source_key, job_id, title, location, employment_type, compensation,
        salary_min, salary_max, salary_currency, salary_period, salary_location, salary_is_estimated,
        department, office, language, updated_at, posted_at, job_url, fetched_at,
        first_seen_at, last_seen_at, seen_run_id, raw_json
      ) VALUES (
        @provider, @source_key, @job_id, @title, @location, @employment_type, @compensation,
        @salary_min, @salary_max, @salary_currency, @salary_period, @salary_location, @salary_is_estimated,
        @department, @office, @language, @updated_at, @posted_at, @job_url, @fetched_at,
        @first_seen_at, @last_seen_at, @seen_run_id, @raw_json
      )
      ON CONFLICT(provider, source_key, job_id) DO UPDATE SET
        title = excluded.title,
        location = excluded.location,
        employment_type = excluded.employment_type,
        compensation = excluded.compensation,
        salary_min = excluded.salary_min,
        salary_max = excluded.salary_max,
        salary_currency = excluded.salary_currency,
        salary_period = excluded.salary_period,
        salary_location = excluded.salary_location,
        salary_is_estimated = excluded.salary_is_estimated,
        department = excluded.department,
        office = excluded.office,
        language = excluded.language,
        updated_at = excluded.updated_at,
        posted_at = excluded.posted_at,
        job_url = excluded.job_url,
        fetched_at = excluded.fetched_at,
        last_seen_at = excluded.last_seen_at,
        seen_run_id = excluded.seen_run_id
    `);
    this.sqliteInsertMany = this.sqliteDb.transaction((rows: NormalizedJob[], runId: string) => {
      const now = new Date().toISOString();
      for (const job of rows) {
        this.sqliteUpsert.run({
          provider: job.provider,
          source_key: job.source_key,
          job_id: job.job_id,
          title: job.title,
          location: job.location,
          employment_type: job.employment_type,
          compensation: job.compensation,
          salary_min: job.salary_min,
          salary_max: job.salary_max,
          salary_currency: job.salary_currency,
          salary_period: job.salary_period,
          salary_location: job.salary_location,
          salary_is_estimated: job.salary_is_estimated ? 1 : 0,
          department: job.department,
          office: job.office,
          language: job.language,
          updated_at: toTimestampOrNull(job.updated_at),
          posted_at: toTimestampOrNull(job.posted_at),
          job_url: job.job_url,
          fetched_at: toTimestampOrNull(job.fetched_at) ?? now,
          first_seen_at: toTimestampOrNull(job.posted_at) ?? toTimestampOrNull(job.fetched_at) ?? now,
          last_seen_at: toTimestampOrNull(job.fetched_at) ?? now,
          seen_run_id: runId,
          raw_json: "null",
        });
      }
    });
    this.sqliteDeleteMissing = this.sqliteDb.prepare(`DELETE FROM catalog_jobs WHERE seen_run_id <> ?`);
    this.sqliteSelectAll = this.sqliteDb.prepare(`
      SELECT provider, source_key, job_id, title, location, employment_type, compensation,
             salary_min, salary_max, salary_currency, salary_period, salary_location, salary_is_estimated,
             department, office, language, updated_at, posted_at, job_url,
             fetched_at, first_seen_at, last_seen_at
      FROM catalog_jobs ORDER BY provider, source_key, job_id
    `);
  }

  private ensureSqliteColumn(table: string, column: string, definition: string): void {
    const rows = this.sqliteDb.prepare(`PRAGMA table_info(${table})`).all() as Array<{ name: string }>;
    if (rows.some((r) => r.name === column)) return;
    this.sqliteDb.exec(`ALTER TABLE ${table} ADD COLUMN ${column} ${definition}`);
  }

  async initialize(): Promise<void> {
    if (this.initialized) return;
    const errors: string[] = [];
    if (this.usePg && this.pgPool) {
      try {
        const client = await this.pgPool.connect();
        try {
          await client.query(`CREATE EXTENSION IF NOT EXISTS pg_trgm`);
          await client.query(`
            CREATE TABLE IF NOT EXISTS catalog_jobs (
              provider TEXT NOT NULL,
              source_key TEXT NOT NULL,
              job_id TEXT NOT NULL,
              title TEXT,
              location TEXT,
              employment_type TEXT,
              compensation TEXT,
              department TEXT,
              office TEXT,
              language TEXT,
              updated_at TIMESTAMPTZ,
              posted_at TIMESTAMPTZ,
              job_url TEXT,
              fetched_at TIMESTAMPTZ NOT NULL,
              first_seen_at TIMESTAMPTZ NOT NULL,
              last_seen_at TIMESTAMPTZ NOT NULL,
              seen_run_id TEXT NOT NULL,
              raw_json TEXT DEFAULT 'null',
              salary_min NUMERIC,
              salary_max NUMERIC,
              salary_currency TEXT,
              salary_period TEXT,
              salary_location TEXT,
              salary_is_estimated SMALLINT DEFAULT 0,
              PRIMARY KEY (provider, source_key, job_id)
            );
          `);
          await client.query(`
            CREATE INDEX IF NOT EXISTS catalog_jobs_seen_run_id_idx ON catalog_jobs(seen_run_id);
            CREATE INDEX IF NOT EXISTS catalog_jobs_last_seen_at_idx ON catalog_jobs(last_seen_at);
            CREATE INDEX IF NOT EXISTS idx_provider ON catalog_jobs(provider);
            CREATE INDEX IF NOT EXISTS idx_location ON catalog_jobs(location);
            CREATE INDEX IF NOT EXISTS idx_posted_at ON catalog_jobs(posted_at DESC NULLS LAST);
            CREATE INDEX IF NOT EXISTS idx_first_seen_at ON catalog_jobs(first_seen_at DESC NULLS LAST);
            CREATE INDEX IF NOT EXISTS idx_source_key ON catalog_jobs(source_key);
            CREATE INDEX IF NOT EXISTS idx_salary_min ON catalog_jobs(salary_min);
            CREATE INDEX IF NOT EXISTS idx_salary_max ON catalog_jobs(salary_max);
            CREATE INDEX IF NOT EXISTS idx_title_trgm ON catalog_jobs USING GIN(title gin_trgm_ops);
            CREATE INDEX IF NOT EXISTS idx_location_trgm ON catalog_jobs USING GIN(location gin_trgm_ops);
          `);
          this.pgInitialized = true;
          console.log("✓ PostgreSQL CatalogStore initialized");
        } finally {
          client.release();
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        console.error("[CatalogStore] Postgres init failed, falling back to sqlite:", msg);
        errors.push(msg);
        this.usePg = false;
        // If we have sqlite backup, continue; otherwise rethrow
        if (!this.useSqlite) throw e;
      }
    }
    if (this.useSqlite) {
      try {
        this.ensureSqlite();
        console.log(`✓ SQLite CatalogStore initialized at ${this.sqlitePath}`);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        console.error("[CatalogStore] SQLite init failed:", msg);
        errors.push(msg);
        this.useSqlite = false;
        if (!this.usePg) throw e;
      }
    }
    if (!this.usePg && !this.useSqlite) {
      throw new Error(`CatalogStore: no driver available (${errors.join("; ")})`);
    }
    this.initialized = true;
  }

  private async withSqliteLock<T>(fn: () => T | Promise<T>): Promise<T> {
    // serialize sqlite writes to avoid SQLITE_BUSY with concurrent workers
    const task = this.sqliteQueue.then(() => fn()) as Promise<T>;
    // keep queue alive even if task fails
    this.sqliteQueue = task.then(() => {}, () => {});
    return task;
  }

  async recordJobs(jobs: NormalizedJob[], runId: string): Promise<void> {
    const tasks: Promise<void>[] = [];
    if (this.usePg && this.pgPool && this.pgInitialized) {
      tasks.push(this.recordJobsPg(jobs, runId));
    }
    if (this.useSqlite) {
      // serialize sqlite writes with retry
      const sqliteTask = this.withSqliteLock(async () => {
        this.ensureSqlite();
        let lastErr: unknown = null;
        for (let attempt = 0; attempt < 3; attempt++) {
          try {
            this.sqliteInsertMany(jobs, runId);
            return;
          } catch (e: any) {
            lastErr = e;
            if (e?.code === "SQLITE_BUSY" && attempt < 2) {
              await new Promise((r) => setTimeout(r, 100 * (attempt + 1)));
              continue;
            }
            console.error("[CatalogStore] SQLite recordJobs error:", e);
            if (!this.usePg) throw e;
            return;
          }
        }
        if (lastErr) {
          console.error("[CatalogStore] SQLite recordJobs failed after retries:", lastErr);
          if (!this.usePg) throw lastErr;
        }
      });
      tasks.push(sqliteTask);
    }
    if (tasks.length > 0) {
      const results = await Promise.allSettled(tasks);
      for (const r of results) if (r.status === "rejected") console.error("[CatalogStore] PG/SQLite recordJobs failed:", r.reason);
      if (results.every((r) => r.status === "rejected") && !this.useSqlite) throw (results[0] as PromiseRejectedResult).reason;
      // if PG failed but sqlite succeeded, still consider success (backup kept)
      const pgFailed = tasks.length > 0 && results[0] && results[0].status === "rejected";
      if (pgFailed && this.useSqlite && results.some((r) => r.status === "fulfilled")) {
        // don't throw – pg error already logged in recordJobsPg
      } else if (results.every((r) => r.status === "rejected")) {
        throw (results.find((r) => r.status === "rejected") as PromiseRejectedResult).reason;
      }
    }
  }

  private async recordJobsPg(jobs: NormalizedJob[], runId: string): Promise<void> {
    if (!this.pgPool) return;
    const now = new Date().toISOString();
    const client = await this.pgPool.connect();
    let inserted = 0;
    try {
      await client.query("BEGIN");
      for (const job of jobs) {
        try {
          const cleanUpdated = toTimestampOrNull(job.updated_at);
          const cleanPosted = toTimestampOrNull(job.posted_at);
          const cleanFetched = toTimestampOrNull(job.fetched_at) ?? now;
          const cleanFirstSeen = cleanPosted ?? cleanFetched ?? now;
          const cleanLastSeen = cleanFetched ?? now;
          await client.query(
            `INSERT INTO catalog_jobs (
              provider, source_key, job_id, title, location, employment_type, compensation,
              department, office, language, updated_at, posted_at, job_url, fetched_at,
              first_seen_at, last_seen_at, seen_run_id, raw_json,
              salary_min, salary_max, salary_currency, salary_period, salary_location, salary_is_estimated
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24)
            ON CONFLICT(provider, source_key, job_id) DO UPDATE SET
              title = EXCLUDED.title, location = EXCLUDED.location, employment_type = EXCLUDED.employment_type,
              compensation = EXCLUDED.compensation, department = EXCLUDED.department, office = EXCLUDED.office,
              language = EXCLUDED.language, updated_at = EXCLUDED.updated_at, posted_at = EXCLUDED.posted_at,
              job_url = EXCLUDED.job_url, fetched_at = EXCLUDED.fetched_at, last_seen_at = EXCLUDED.last_seen_at,
              seen_run_id = EXCLUDED.seen_run_id, salary_min = EXCLUDED.salary_min, salary_max = EXCLUDED.salary_max,
              salary_currency = EXCLUDED.salary_currency, salary_period = EXCLUDED.salary_period,
              salary_location = EXCLUDED.salary_location, salary_is_estimated = EXCLUDED.salary_is_estimated`,
            [
              job.provider, job.source_key, job.job_id, job.title, job.location, job.employment_type, job.compensation,
              job.department, job.office, job.language, cleanUpdated, cleanPosted, job.job_url, cleanFetched,
              cleanFirstSeen, cleanLastSeen, runId, "null",
              job.salary_min, job.salary_max, job.salary_currency, job.salary_period, job.salary_location,
              job.salary_is_estimated ? 1 : 0,
            ]
          );
          inserted++;
        } catch (rowErr) {
          console.error(`[CatalogStore] PG skip job ${job.provider}/${job.source_key}/${job.job_id} due to row error:`, rowErr);
          // continue to next job – don't abort whole batch
        }
      }
      await client.query("COMMIT");
      console.log(`[CatalogStore] PG inserted ${inserted}/${jobs.length} jobs for run ${runId}`);
    } catch (error) {
      try { await client.query("ROLLBACK"); } catch {}
      throw error;
    } finally {
      client.release();
    }
  }

  async finalizeRun(runId: string): Promise<void> {
    if (this.usePg && this.pgPool && this.pgInitialized) {
      const client = await this.pgPool.connect();
      try {
        await client.query("DELETE FROM catalog_jobs WHERE seen_run_id <> $1", [runId]);
      } finally {
        client.release();
      }
    }
    if (this.useSqlite && this.sqliteDb) {
      try {
        await this.withSqliteLock(() => {
          this.ensureSqlite();
          this.sqliteDeleteMissing.run(runId);
        });
      } catch (e) {
        console.error("[CatalogStore] SQLite finalizeRun error:", e);
        if (!this.usePg) throw e;
      }
    }
  }

  async exportJsonl(filePath: string): Promise<void> {
    await mkdir(dirname(filePath), { recursive: true });
    const tempPath = `${filePath}.tmp`;
    // Prefer PG if available, else sqlite
    if (this.usePg && this.pgPool && this.pgInitialized) {
      const client = await this.pgPool.connect();
      try {
        const result = await client.query(`
          SELECT provider, source_key, job_id, title, location, employment_type, compensation,
                 salary_min, salary_max, salary_currency, salary_period, salary_location,
                 salary_is_estimated, department, office, language, updated_at, posted_at, job_url,
                 fetched_at, first_seen_at, last_seen_at
          FROM catalog_jobs ORDER BY provider, source_key, job_id`);
        const lines = Readable.from((function* () { for (const row of result.rows) yield `${JSON.stringify(row)}\n`; })(), { encoding: "utf8" });
        await pipeline(lines, createWriteStream(tempPath));
        await rename(tempPath, filePath);
        return;
      } finally {
        client.release();
      }
    }
    // fallback sqlite
    this.ensureSqlite();
    const rows = this.sqliteSelectAll.iterate([]) as Iterable<CatalogExportRow>;
    const lines = Readable.from((function* () { for (const row of rows) yield `${JSON.stringify(row)}\n`; })(), { encoding: "utf8" });
    await pipeline(lines, createWriteStream(tempPath));
    await rename(tempPath, filePath);
  }

  async close(): Promise<void> {
    if (this.pgPool) await this.pgPool.end();
    if (this.sqliteDb) try { this.sqliteDb.close(); } catch {}
  }
}
