/**
 * Hybrid Database Layer: Postgres primary + SQLite fallback
 * - CATALOG_DRIVER=postgres -> only postgres
 * - CATALOG_DRIVER=sqlite   -> only sqlite
 * - CATALOG_DRIVER=auto     -> postgres if PG_HOST/DATABASE_URL set else sqlite; on pg failure fallback to sqlite
 */

import pg from "pg";

const CATALOG_DRIVER = (process.env.CATALOG_DRIVER || "auto").toLowerCase();
const CATALOG_DB = process.env.CATALOG_DB || "/app/state/catalog.sqlite";
const SHOULD_TRY_PG = (() => {
  if (CATALOG_DRIVER === "sqlite") return false;
  if (CATALOG_DRIVER === "postgres") return true;
  // auto
  if (process.env.DATABASE_URL) return true;
  if (process.env.PG_HOST) return true;
  return false;
})();

let pgPool: pg.Pool | null = null;
let sqliteDb: any = null;
let driver: "pg" | "sqlite" = SHOULD_TRY_PG ? "pg" : "sqlite";
let pgFailed = false;

function createPgPool(): pg.Pool {
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

if (driver === "pg") {
  pgPool = createPgPool();
}

async function ensureSqlite(): Promise<void> {
  if (sqliteDb) return;
  try {
    const mod: any = await import("better-sqlite3");
    const BetterSqlite3 = mod.default ?? mod;
    sqliteDb = new BetterSqlite3(CATALOG_DB);
    sqliteDb.pragma("busy_timeout = 30000");
  } catch (e) {
    console.error("[db] failed to open sqlite:", e);
    throw e;
  }
}

// Translate postgres SQL to sqlite when driver is sqlite
function translateForSqlite(sql: string): string {
  let s = sql;
  // $1, $2 -> ?
  s = s.replace(/\$\d+/g, "?");
  // ILIKE -> LIKE (sqlite LIKE is case-insensitive for ASCII by default; use COLLATE NOCASE)
  s = s.replace(/ ILIKE /g, " LIKE ");
  s = s.replace(/ ILIKE\(/g, " LIKE(");
  // NOW() - INTERVAL 'X days' -> datetime('now', '-X days')
  s = s.replace(/NOW\(\)\s*-\s*INTERVAL\s*'(\d+)\s+days?'/gi, "datetime('now', '-$1 days')");
  s = s.replace(/NOW\(\)/g, "datetime('now')");
  // Remove NULLS LAST / NULLS FIRST (sqlite doesn't support)
  s = s.replace(/\s+NULLS\s+(LAST|FIRST)/gi, "");
  // TRIM(compensation) = '' handling stays
  // to_tsvector etc not expected
  return s;
}

async function pgQuery(sql: string, params: unknown[]): Promise<pg.QueryResult> {
  if (!pgPool) throw new Error("pgPool not initialized");
  return pgPool.query(sql, params);
}

export class Database {
  async query(sql: string, params: unknown[] = []): Promise<unknown[]> {
    if (driver === "pg") {
      try {
        const result = await pgQuery(sql, params);
        return result.rows;
      } catch (e: any) {
        // Transient pg failure: try sqlite fallback for this query only if auto mode
        if (SHOULD_TRY_PG && CATALOG_DRIVER === "auto") {
          console.warn("[db] pg query failed, falling back to sqlite for this query:", e?.message);
          try {
            await ensureSqlite();
            const sqliteSql = translateForSqlite(sql);
            const stmt = sqliteDb.prepare(sqliteSql);
            return stmt.all(...params) as unknown[];
          } catch (sqliteErr) {
            throw e; // throw original pg error
          }
        }
        throw e;
      }
    }
    await ensureSqlite();
    const sqliteSql = translateForSqlite(sql);
    const stmt = sqliteDb.prepare(sqliteSql);
    return stmt.all(...params) as unknown[];
  }

  async queryOne(sql: string, params: unknown[] = []): Promise<Record<string, unknown> | null> {
    if (driver === "pg") {
      try {
        const result = await pgQuery(sql, params);
        return (result.rows[0] as Record<string, unknown>) || null;
      } catch (e: any) {
        if (SHOULD_TRY_PG && CATALOG_DRIVER === "auto") {
          console.warn("[db] pg queryOne failed, falling back to sqlite for this query:", e?.message);
          try {
            await ensureSqlite();
            const sqliteSql = translateForSqlite(sql);
            const stmt = sqliteDb.prepare(sqliteSql);
            return (stmt.get(...params) as Record<string, unknown>) || null;
          } catch {
            throw e;
          }
        }
        throw e;
      }
    }
    await ensureSqlite();
    const sqliteSql = translateForSqlite(sql);
    const stmt = sqliteDb.prepare(sqliteSql);
    return (stmt.get(...params) as Record<string, unknown>) || null;
  }

  async queryCount(sql: string, params: unknown[] = []): Promise<number> {
    const row = await this.queryOne(sql, params);
    if (!row) return 0;
    const val = (row as any).count ?? (row as any).n ?? Object.values(row)[0];
    return parseInt(String(val), 10) || 0;
  }

  // For compatibility with old code that expects sync prepare – expose async wrappers
  prepare(sql: string) {
    return {
      all: (...params: unknown[]) => this.query(sql, params),
      get: (...params: unknown[]) => this.queryOne(sql, params),
      run: (...params: unknown[]) => this.query(sql, params),
    };
  }

  async exec(sql: string): Promise<void> {
    if (driver === "pg") {
      try {
        await pgQuery(sql, []);
        return;
      } catch (e) {
        if (SHOULD_TRY_PG && CATALOG_DRIVER === "auto") {
          await ensureSqlite();
          sqliteDb.exec(translateForSqlite(sql));
          return;
        }
        throw e;
      }
    }
    await ensureSqlite();
    sqliteDb.exec(translateForSqlite(sql));
  }

  async close(): Promise<void> {
    if (pgPool) await pgPool.end();
    if (sqliteDb) try { sqliteDb.close(); } catch {}
  }

  getDriver(): string {
    return driver;
  }
}

export default new Database();
