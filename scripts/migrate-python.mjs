#!/usr/bin/env node
/**
 * Migration using Python's sqlite3 module to extract, then Node.js pg for insert
 */

import pg from "pg";
import { spawn } from "child_process";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SQLITE_DB = path.join(__dirname, "../state/catalog.sqlite");

const PG_HOST = process.env.PG_HOST || "localhost";
const PG_PORT = process.env.PG_PORT || 5432;
const PG_DB = process.env.PG_DB || "job_catalog";
const PG_USER = process.env.PG_USER || "job_admin";
const PG_PASSWORD = process.env.PG_PASSWORD || "job_admin_password";

async function readSqliteWithPython() {
  return new Promise((resolve, reject) => {
    const pythonCode = `
import sqlite3
import json
conn = sqlite3.connect(r'${SQLITE_DB}')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()
cursor.execute('SELECT * FROM catalog_jobs')
rows = cursor.fetchall()
for row in rows:
    print(json.dumps(dict(row)))
conn.close()
`;

    const python = spawn("python3", ["-c", pythonCode]);
    let output = "";
    let errorOutput = "";

    python.stdout.on("data", (data) => {
      output += data.toString();
    });

    python.stderr.on("data", (data) => {
      errorOutput += data.toString();
    });

    python.on("close", (code) => {
      if (code === 0) {
        resolve(output);
      } else {
        reject(new Error(`Python error: ${errorOutput}`));
      }
    });
  });
}

async function migrate() {
  console.log("Starting SQLite → PostgreSQL migration (via Python)...\n");

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

    console.log("Reading SQLite database with Python...");
    const jsonLines = await readSqliteWithPython();
    const lines = jsonLines.trim().split("\n").filter((l) => l.length > 0);
    const total = lines.length;

    console.log(`✓ Read ${total.toLocaleString()} jobs from SQLite\n`);

    if (total === 0) {
      console.log("No data to migrate.");
      await pgClient.end();
      process.exit(0);
    }

    // Insert in batches
    const BATCH_SIZE = 1000;
    let inserted = 0;

    for (let i = 0; i < lines.length; i += BATCH_SIZE) {
      const batch = lines.slice(i, i + BATCH_SIZE);
      
      for (const line of batch) {
        try {
          const job = JSON.parse(line);
          await pgClient.query(
            `INSERT INTO catalog_jobs 
            (provider, source_key, job_id, title, location, employment_type, compensation,
             salary_min, salary_max, salary_currency, salary_period, salary_location,
             salary_is_estimated, department, job_url, updated_at, posted_at, first_seen_at, last_seen_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)`,
            [
              job.provider, job.source_key, job.job_id, job.title, job.location,
              job.employment_type, job.compensation, job.salary_min, job.salary_max,
              job.salary_currency, job.salary_period, job.salary_location,
              job.salary_is_estimated, job.department, job.job_url, job.updated_at,
              job.posted_at, job.first_seen_at, job.last_seen_at,
            ]
          );
          inserted++;
        } catch (e) {
          // Duplicate key or constraint - skip
        }
      }

      const pct = ((i + BATCH_SIZE) / total * 100).toFixed(1);
      console.log(`Inserted ${Math.min(i + BATCH_SIZE, total).toLocaleString()} / ${total.toLocaleString()} (${pct}%)`);
    }

    console.log(`\n✓ Migration complete! Inserted ${inserted.toLocaleString()} jobs\n`);

    // Verify
    const result = await pgClient.query("SELECT COUNT(*) as count FROM catalog_jobs");
    const finalCount = result.rows[0].count;
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
