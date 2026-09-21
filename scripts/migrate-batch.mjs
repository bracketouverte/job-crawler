#!/usr/bin/env node
/**
 * Batch migration from SQLite to PostgreSQL using COPY
 * Exports CSV from SQLite and imports to PostgreSQL in batches
 */

import pg from "pg";
import { spawn } from "child_process";
import { createWriteStream } from "fs";

const PG_HOST = process.env.PG_HOST || "localhost";
const PG_PORT = process.env.PG_PORT || 5432;
const PG_DB = process.env.PG_DB || "job_catalog";
const PG_USER = process.env.PG_USER || "job_admin";
const PG_PASSWORD = process.env.PG_PASSWORD || "job_admin_password";
const SQLITE_DB = process.env.SQLITE_DB || "/app/crawler/state/catalog.sqlite";

async function migrate() {
  console.log("Starting SQLite → PostgreSQL batch migration...\n");

  const pgClient = new pg.Client({
    host: PG_HOST,
    port: PG_PORT,
    database: PG_DB,
    user: PG_USER,
    password: PG_PASSWORD,
  });

  try {
    await pgClient.connect();
    console.log(`✓ Connected to PostgreSQL at ${PG_HOST}:${PG_PORT}`);

    // Clear existing
    console.log("Clearing existing data...");
    await pgClient.query("DELETE FROM catalog_jobs");

    // Stream export from SQLite and import to PostgreSQL
    console.log("Exporting from SQLite and importing to PostgreSQL...\n");

    const sqlite3 = spawn("sqlite3", [
      SQLITE_DB,
      ".mode csv",
      ".headers off",
      "SELECT * FROM catalog_jobs",
    ]);

    let lineCount = 0;
    let batch = [];
    const BATCH_SIZE = 5000;

    for await (const line of sqlite3.stdout) {
      if (!line.trim()) continue;

      lineCount++;
      batch.push(line.toString());

      if (batch.length >= BATCH_SIZE) {
        // Insert batch
        const csvData = batch.join("\n");
        try {
          await pgClient.query(
            `COPY catalog_jobs FROM STDIN WITH CSV`,
            [csvData]
          );
        } catch (e) {
          // Try individual rows on batch failure
          for (const row of batch) {
            try {
              const values = row.split(",").map((v) => (v === "" || v === "null" ? null : v));
              await pgClient.query(
                `INSERT INTO catalog_jobs 
                (provider, source_key, job_id, title, location, employment_type, compensation,
                 salary_min, salary_max, salary_currency, salary_period, salary_location,
                 salary_is_estimated, department, job_url, updated_at, posted_at, first_seen_at, last_seen_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)`,
                values
              );
            } catch (rowError) {
              // Skip duplicate/constraint errors
            }
          }
        }

        console.log(`Processed ${lineCount.toLocaleString()} rows...`);
        batch = [];
      }
    }

    // Final batch
    if (batch.length > 0) {
      const csvData = batch.join("\n");
      try {
        await pgClient.query(`COPY catalog_jobs FROM STDIN WITH CSV`, [csvData]);
      } catch (e) {
        for (const row of batch) {
          try {
            const values = row.split(",").map((v) => (v === "" || v === "null" ? null : v));
            await pgClient.query(
              `INSERT INTO catalog_jobs VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)`,
              values
            );
          } catch {}
        }
      }
    }

    console.log(`\n✓ Exported and processed ${lineCount.toLocaleString()} rows\n`);

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
