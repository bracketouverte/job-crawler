import { createWriteStream } from "node:fs";
import { mkdir, rename } from "node:fs/promises";
import { dirname } from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import Database from "better-sqlite3";
import { NormalizedJob } from "./types.js";

type CatalogRow = {
  provider: string;
  source_key: string;
  job_id: string;
  title: string | null;
  location: string | null;
  employment_type: string | null;
  compensation: string | null;
  department: string | null;
  office: string | null;
  language: string | null;
  updated_at: string | null;
  job_url: string | null;
  fetched_at: string;
  first_seen_at: string;
  last_seen_at: string;
  seen_run_id: string;
};

type CatalogExportRow = Omit<CatalogRow, "seen_run_id">;

export class CatalogStore {
  private readonly db: ReturnType<typeof Database>;
  private readonly upsertOne: ReturnType<ReturnType<typeof Database>["prepare"]>;
  private readonly insertMany: (rows: NormalizedJob[], runId: string) => void;
  private readonly deleteMissingStatement: ReturnType<ReturnType<typeof Database>["prepare"]>;
  private readonly selectAllStatement: ReturnType<ReturnType<typeof Database>["prepare"]>;

  constructor(dbPath: string) {
    this.db = new Database(dbPath);
    this.db.pragma("journal_mode = WAL");
    this.db.pragma("synchronous = NORMAL");
    this.db.pragma("foreign_keys = ON");
    this.db.exec(`
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
        job_url TEXT,
        fetched_at TEXT NOT NULL,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        seen_run_id TEXT NOT NULL,
        raw_json TEXT NOT NULL DEFAULT 'null',
        PRIMARY KEY (provider, source_key, job_id)
      );
      CREATE INDEX IF NOT EXISTS catalog_jobs_seen_run_id_idx ON catalog_jobs(seen_run_id);
      CREATE INDEX IF NOT EXISTS catalog_jobs_last_seen_at_idx ON catalog_jobs(last_seen_at);
      DROP INDEX IF EXISTS catalog_jobs_title_lower_idx;
      DROP INDEX IF EXISTS catalog_jobs_location_lower_idx;
    `);

    this.upsertOne = this.db.prepare(`
      INSERT INTO catalog_jobs (
        provider,
        source_key,
        job_id,
        title,
        location,
        employment_type,
        compensation,
        department,
        office,
        language,
        updated_at,
        job_url,
        fetched_at,
        first_seen_at,
        last_seen_at,
        seen_run_id,
        raw_json
      ) VALUES (
        @provider,
        @source_key,
        @job_id,
        @title,
        @location,
        @employment_type,
        @compensation,
        @department,
        @office,
        @language,
        @updated_at,
        @job_url,
        @fetched_at,
        @first_seen_at,
        @last_seen_at,
        @seen_run_id,
        @raw_json
      )
      ON CONFLICT(provider, source_key, job_id) DO UPDATE SET
        title = excluded.title,
        location = excluded.location,
        employment_type = excluded.employment_type,
        compensation = excluded.compensation,
        department = excluded.department,
        office = excluded.office,
        language = excluded.language,
        updated_at = excluded.updated_at,
        job_url = excluded.job_url,
        fetched_at = excluded.fetched_at,
        last_seen_at = excluded.last_seen_at,
        seen_run_id = excluded.seen_run_id
    `);
    this.insertMany = this.db.transaction((rows: NormalizedJob[], runId: string) => {
      const now = new Date().toISOString();
      for (const job of rows) {
        this.upsertOne.run({
          provider: job.provider,
          source_key: job.source_key,
          job_id: job.job_id,
          title: job.title,
          location: job.location,
          employment_type: job.employment_type,
          compensation: job.compensation,
          department: job.department,
          office: job.office,
          language: job.language,
          updated_at: job.updated_at,
          job_url: job.job_url,
          fetched_at: job.fetched_at,
          first_seen_at: job.fetched_at ?? now,
          last_seen_at: job.fetched_at ?? now,
          seen_run_id: runId,
          raw_json: "null"
        });
      }
    });
    this.deleteMissingStatement = this.db.prepare(`DELETE FROM catalog_jobs WHERE seen_run_id <> ?`);
    this.selectAllStatement = this.db.prepare(`
      SELECT
        provider,
        source_key,
        job_id,
        title,
        location,
        employment_type,
        compensation,
        department,
        office,
        language,
        updated_at,
        job_url,
        fetched_at,
        first_seen_at,
        last_seen_at
      FROM catalog_jobs
      ORDER BY provider, source_key, job_id
    `);
  }

  recordJobs(jobs: NormalizedJob[], runId: string): void {
    this.insertMany(jobs, runId);
  }

  finalizeRun(runId: string): void {
    this.deleteMissingStatement.run(runId);
  }

  async exportJsonl(filePath: string): Promise<void> {
    await mkdir(dirname(filePath), { recursive: true });
    const tempPath = `${filePath}.tmp`;

    const rows = this.selectAllStatement.iterate([]) as Iterable<CatalogExportRow>;
    const lines = Readable.from(
      (function* () {
        for (const row of rows) {
          yield `${JSON.stringify(row)}\n`;
        }
      })(),
      { encoding: "utf8" }
    );

    await pipeline(lines, createWriteStream(tempPath));
    await rename(tempPath, filePath);
  }

  close(): void {
    this.db.close();
  }
}
