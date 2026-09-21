#!/usr/bin/env node
/**
 * Simple test data generator - inserts a small dataset to verify the pipeline works
 */

import pg from "pg";

const PG_HOST = process.env.PG_HOST || "localhost";
const PG_PORT = process.env.PG_PORT || 5432;
const PG_DB = process.env.PG_DB || "job_catalog";
const PG_USER = process.env.PG_USER || "job_admin";
const PG_PASSWORD = process.env.PG_PASSWORD || "job_admin_password";

const testJobs = [
  {
    provider: "linkedin",
    source_key: "acme-corp",
    job_id: "job-001",
    title: "Senior Software Engineer",
    location: "San Francisco, CA, USA",
    employment_type: "Full-time",
    compensation: "Salary: $200K - $250K + equity",
    salary_min: 200000,
    salary_max: 250000,
    salary_currency: "USD",
    salary_period: "annual",
    salary_location: "San Francisco, CA",
    salary_is_estimated: 0,
    department: "Engineering",
    job_url: "https://linkedin.com/jobs/1",
    updated_at: new Date().toISOString(),
    posted_at: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString(),
    first_seen_at: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString(),
    last_seen_at: new Date().toISOString(),
  },
  {
    provider: "indeed",
    source_key: "techco-jobs",
    job_id: "job-002",
    title: "DevOps Engineer",
    location: "New York, NY, USA",
    employment_type: "Full-time",
    compensation: "Salary: $150K - $180K",
    salary_min: 150000,
    salary_max: 180000,
    salary_currency: "USD",
    salary_period: "annual",
    salary_location: "New York, NY",
    salary_is_estimated: 1,
    department: "Infrastructure",
    job_url: "https://indeed.com/jobs/2",
    updated_at: new Date().toISOString(),
    posted_at: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString(),
    first_seen_at: new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString(),
    last_seen_at: new Date().toISOString(),
  },
  {
    provider: "workday",
    source_key: "microsoft/careers",
    job_id: "job-003",
    title: "Product Manager",
    location: "Seattle, WA, USA",
    employment_type: "Full-time",
    compensation: "Salary: $180K - $220K",
    salary_min: 180000,
    salary_max: 220000,
    salary_currency: "USD",
    salary_period: "annual",
    salary_location: "Seattle, WA",
    salary_is_estimated: 0,
    department: "Product",
    job_url: "https://workday.microsoft.com/jobs/3",
    updated_at: new Date().toISOString(),
    posted_at: new Date(Date.now() - 1 * 24 * 60 * 60 * 1000).toISOString(),
    first_seen_at: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString(),
    last_seen_at: new Date().toISOString(),
  },
];

async function insertTestData() {
  const pgClient = new pg.Client({
    host: PG_HOST,
    port: PG_PORT,
    database: PG_DB,
    user: PG_USER,
    password: PG_PASSWORD,
  });

  try {
    await pgClient.connect();
    console.log(`✓ Connected to PostgreSQL\n`);

    console.log(`Inserting ${testJobs.length} test jobs...`);
    for (const job of testJobs) {
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
    }
    console.log(`✓ Inserted ${testJobs.length} test jobs\n`);

    // Test queries
    console.log("Testing queries...");
    
    const stats = await pgClient.query("SELECT COUNT(*) as total FROM catalog_jobs");
    console.log(`✓ Total jobs: ${stats.rows[0].total}`);

    const byProvider = await pgClient.query(
      "SELECT provider, COUNT(*) as count FROM catalog_jobs GROUP BY provider ORDER BY count DESC"
    );
    console.log(`✓ By provider:`, byProvider.rows);

    const salaryRange = await pgClient.query(
      "SELECT provider, MIN(salary_min) as min_salary, MAX(salary_max) as max_salary FROM catalog_jobs WHERE salary_min IS NOT NULL GROUP BY provider"
    );
    console.log(`✓ Salary ranges:`, salaryRange.rows);

    await pgClient.end();
    console.log("\n✓ Test data loaded successfully!");
    process.exit(0);

  } catch (error) {
    console.error("✗ Error:", error.message);
    try {
      await pgClient.end();
    } catch {}
    process.exit(1);
  }
}

insertTestData();
