# job-scrapper

## What Is It

`job-scrapper` is a small job-intelligence stack for public ATS job boards.

It has three main modules:

- `crawler/` collects public job postings from providers like Greenhouse, Lever, Ashby, BambooHR, Teamtailor, Workday, and Workable.
- `matcher/` extracts structured job-post data from a posting URL and runs fit analysis against a profile.
- `viewer/` serves a local job-feed UI over the crawler catalog, with favorites, saved searches, JD inspection, and matcher-backed fit analysis.

The profile files under `matcher/$CAREER_OPS_DIR/` are generated local assets from `career-ops`:
https://github.com/santifer/career-ops

## Features

- Crawl multiple ATS providers into a normalized job catalog.
- Persist jobs in SQLite and export the latest snapshot as JSONL.
- Parse compensation data and extract salary ranges from job postings.
- Filter jobs by salary range at crawl time (block jobs outside target band) or at query time (UI filtering).
- Parse a single posting URL into structured fields such as title, location, employment type, workplace type, requirements, and responsibilities.
- Run both quick-fit and full-fit job scoring with NVIDIA NIM.
- Browse the local catalog from a local job-feed UI with saved searches, favorites, salary filtering, and fit-analysis workflows.
- Run the whole stack with Docker Compose.

## Quick Start

### 1. Start from Docker Compose

Build and use the services from the repo root:

```bash
docker compose build
```

### 2. Crawl job boards

Run with catalog persistence (SQLite + JSONL output):

```bash
docker compose run --rm crawler \
  --concurrency 8 \
  --provider-concurrency ashby=1,workday=4,lever=3,teamtailor=2,bamboohr=3,greenhouse=6,workable=2 \
  --timeout-ms 30000 \
  --retries 5 \
  --exclude-sources /app/state/exclude.jsonl \
  --catalog-db /app/state/catalog.sqlite \
  --catalog-file /app/output/current-jobs.jsonl
```

Outputs:

- SQLite catalog: `crawler/state/catalog.sqlite`
- Jobs JSONL: `crawler/output/current-jobs.jsonl`
- Report: `crawler/output/report.json`

`exclude.jsonl` is updated automatically after a successful crawl run. Sources that return permanent `404`/`410` failures are appended to the quarantine file and skipped on later runs.

Complete parameter list:

```text
--sources <dir>          Source JSON directory (default: /data/sources)
--providers <list|all>   Providers to crawl (default: all)
--concurrency <n>        Global source concurrency (default: 50)
--out <file>             JSONL output path (default: /app/output/jobs.jsonl)
--report <file>          Report JSON path (default: /app/output/report.json)
--catalog-db <file>      SQLite catalog state file (default: /app/state/catalog.sqlite)
--exclude-sources <file> JSONL source quarantine file
--sample <n>             Crawl only first n sources per provider
--max-jobs-per-source <n> Emit at most n jobs per source
--max-age-hours <n>      Keep only jobs where updated_at is within last n hours
--progress-every-ms <n>  Progress log interval, 0 disables it (default: 10000)
--provider-concurrency <spec> Per-provider limits, e.g. ashby=2,workday=10 (default: ashby=2)
--timeout-ms <n>         Per-request timeout (default: 15000)
--retries <n>            Transient retry count (default: 2)
```

### 3. Parse a job posting URL

```bash
docker compose run --rm job-parser \
  --url 'https://job-boards.greenhouse.io/marqeta/jobs/7711098' \
  --pretty
```

### 4. Run a job fit analysis

```bash
docker compose run --rm matcher \
  -j /app/.tmp_marqeta_7711098.txt \
  -p /app \
  -o /app/.tmp_marqeta_7711098_report.json
```

Batch analysis of structured job payloads:

```bash
docker compose run --rm matcher \
  --jobs-jsonl /app/jobs.jsonl \
  --results-jsonl /app/results.jsonl \
  -p /app
```

The default quick-fit pipeline uses `meta/llama-4-maverick-17b-128e-instruct`. A separate full-fit ensemble pipeline is available under `matcher/ensemble_runner.py` for multi-model scoring plus synthesis.

`CAREER_OPS_DIR` is configured in `.env` and `.env.example`, so each user can choose their own local folder name under `matcher/`. Those generated profile files are intentionally not tracked in Git.

### 5. Start the local viewer

```bash
docker compose up viewer
```

Open `http://localhost:3000`.

The viewer can trigger quick-fit and full-fit analysis runs directly from the UI, inspect parsed JD data for a job, and reuse saved searches from `viewer/public/saved-searches.json`.

### 6. Run the crawler on a schedule

```bash
docker compose up -d scheduler
```

The `scheduler` service runs the crawler on a daytime schedule and avoids rerunning if the most recent run was too recent. It uses the same crawler defaults shown above, including automatic exclusion-file updates.

## Tech Stack

- TypeScript + Node.js for the crawler and viewer
- Python 3.12 for parsing and fit analysis
- SQLite for the local job catalog
- Docker Compose for local orchestration
- NVIDIA NIM for fit-analysis inference
- Public ATS APIs and page metadata from Greenhouse, Lever, Ashby, BambooHR, Teamtailor, Workday, and Workable

## Module Docs

- [crawler/README.md](crawler/README.md)
- [matcher/README.md](matcher/README.md)
- [viewer/README.md](viewer/README.md)

## Let's Connect

[![LinkedIn](https://img.shields.io/badge/LinkedIn-Michael%20Levy-0A66C2?style=for-the-badge&logo=linkedin&logoColor=white)](https://www.linkedin.com/in/michael-levy-product/)
