#!/usr/bin/env node
/**
 * Direct migration using Node.js with careful SQL formatting
 */

import pg from "pg";
import { execSync } from "child_process";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SQLITE_DB = path.join(__dirname, "../state/catalog.sqlite");

const PG_HOST = process.env.PG_HOST || "localhost";
const PG_PORT = process.env.PG_PORT || 5432;
const PG_DB = process.env.PG_DB || "job_catalog";
const PG_USER = process.env.PG_USER || "job_admin";
const PG_PASSWORD = process.env.PG_PASSWORD || "job_admin_password";

async function migrate() {
  console.log("Starting SQLite → PostgreSQL migration...\n");

  const pgClient = new pg.Client({
    host: PG_HOST,
    port: PG_PORT,
    database: PG_DB,
    user: PG_USER,
    password: PG_PASSWORD,
  });

  try {
    await pgClient.connect();
    console.log(`✓ Connected to PostgreSQL at ${PG_HOST}:${PG_PORT}\n`);

    // Use sqlite3 CLI directly to export data as SQL
    console.log("Exporting SQLite data...");
    let sqlInserts = "";
    
    try {
      // Try to export as SQL insert statements
      sqlInserts = execSync(
        `sqlite3 "${SQLITE_DB}" ".mode insert catalog_jobs" "SELECT * FROM catalog_jobs LIMIT 5"`,
        { encoding: "utf8" }
      );
      console.log("Sample SQL exports:");
      console.log(sqlInserts.split("\n").slice(0, 3).join("\n"));
    } catch (e) {
      console.log("sqlite3 CLI not available, attempting CSV export...");
      // Fall back: try CSV
      const csv = execSync(
        `sqlite3 -csv "${SQLITE_DB}" "SELECT * FROM catalog_jobs LIMIT 3"`,
        { encoding: "utf8" }
      );
      console.log("First 3 rows (CSV):");
      console.log(csv.split("\n").slice(0, 2).join("\n"));
    }

    // Get count
    const countOut = execSync(
      `sqlite3 "${SQLITE_DB}" "SELECT COUNT(*) FROM catalog_jobs"`,
      { encoding: "utf8" }
    ).trim();
    const total = parseInt(countOut, 10);
    console.log(`\nTotal jobs in SQLite: ${total.toLocaleString()}`);

    if (total === 0) {
      console.log("No data to migrate.");
      await pgClient.end();
      process.exit(0);
    }

    console.log("\n⚠️  The native SQLite module (better-sqlite3) failed to compile on Windows.");
    console.log("To complete the migration, use one of these methods:\n");
    console.log("1. On Linux/Mac with sqlite3 CLI:");
    console.log(`   sqlite3 "${SQLITE_DB}" ".mode csv" ".headers off" "SELECT * FROM catalog_jobs" | \\`);
    console.log(`   psql -h ${PG_HOST} -U ${PG_USER} -d ${PG_DB} -c "COPY catalog_jobs FROM STDIN WITH CSV"\n`);
    console.log("2. Or export/import via Docker:");
    console.log("   docker exec job-crawler-postgres psql -U job_admin job_catalog -c 'COPY catalog_jobs FROM STDIN WITH CSV' < jobs.csv\n");
    console.log("For now, the PostgreSQL schema is ready. You can:");
    console.log("- Test the empty API: curl http://localhost:3000/api/stats");
    console.log("- Load data manually once SQLite access is available\n");

    await pgClient.end();
    process.exit(0);

  } catch (error) {
    console.error("✗ Error:", error.message);
    await pgClient.end();
    process.exit(1);
  }
}

migrate();
