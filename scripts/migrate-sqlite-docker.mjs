#!/usr/bin/env node
/**
 * Migration: SQLite → PostgreSQL using Docker sqlite3 export
 */

import pg from "pg";
import { execSync } from "child_process";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SQLITE_DB = path.join(__dirname, "../crawler/state/catalog.sqlite");

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

    // Clear existing data
    console.log("Clearing existing data...");
    await pgClient.query("DELETE FROM catalog_jobs");

    // Export SQLite as SQL insert statements using Docker
    console.log("Exporting SQLite data via Docker...");
    const sqlOutput = execSync(
      `docker run --rm -v "${SQLITE_DB}:/db.sqlite:ro" keinos/sqlite3 sqlite3 /db.sqlite ".mode insert catalog_jobs" "SELECT * FROM catalog_jobs"`,
      { encoding: "utf8", stdio: ["pipe", "pipe", "pipe"] }
    );

    const lines = sqlOutput
      .split("\n")
      .filter((line) => line.trim().startsWith("INSERT INTO"));

    console.log(`✓ Got ${lines.length} INSERT statements\n`);

    // Execute each INSERT
    let inserted = 0;
    for (const line of lines) {
      try {
        // Convert SQLite INSERT to PostgreSQL-compatible format
        const pgInsert = line
          .replace(/INSERT INTO catalog_jobs VALUES\(/g, "INSERT INTO catalog_jobs VALUES (")
          .replace(/'/g, "''")
          .replace(/NULL/g, "null");

        await pgClient.query(pgInsert);
        inserted++;

        if (inserted % 1000 === 0) {
          console.log(`Inserted ${inserted}/${lines.length}...`);
        }
      } catch (e) {
        // Duplicate or constraint error - skip
        if (!String(e).includes("duplicate") && !String(e).includes("constraint")) {
          console.error(`Error on row ${inserted}:`, e.message);
        }
      }
    }

    console.log(`\n✓ Migration complete! Inserted ${inserted} jobs\n`);

    // Verify
    const result = await pgClient.query("SELECT COUNT(*) as count FROM catalog_jobs");
    const finalCount = parseInt(String(result.rows[0].count), 10);
    console.log(`✓ PostgreSQL now has ${finalCount.toLocaleString()} jobs\n`);

    await pgClient.end();
    process.exit(0);

  } catch (error) {
    console.error("✗ Error:", error.message);
    try {
      await pgClient.end();
    } catch {}
    process.exit(1);
  }
}

migrate();
