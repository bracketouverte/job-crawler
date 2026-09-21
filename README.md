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
- Persist jobs in Postgres (primary) with SQLite as offline backup and export the latest snapshot as JSONL.
- Parse a single posting URL into structured fields such as title, location, employment type, workplace type, requirements, and responsibilities.
- Run both quick-fit and full-fit job scoring with NVIDIA NIM.
- Browse the local catalog from a local job-feed UI with saved searches, favorites, and fit-analysis workflows.
- Run the whole stack with Docker Compose.

## Quick Start

### 1. Start from Docker Compose

Build and use the services from the repo root:

```bash
docker compose build
```

This starts `postgres` (`job-crawler-postgres`, healthchecked, `init-db.sql` schema) as the primary catalog store. Configure via `.env` / `.env.example` (`PG_HOST`, `PG_PORT`, `PG_DB`, `PG_USER`, `PG_PASSWORD`, `DATABASE_URL`, `CATALOG_DRIVER`).

### 2. Crawl job boards

Run with catalog persistence (Postgres primary + SQLite offline backup + JSONL snapshot):

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

Datasource: when run via `docker compose`, the crawler uses **Postgres as primary** via `PG_HOST`/`PG_PORT`/`PG_DB`/`PG_USER`/`PG_PASSWORD` (or `DATABASE_URL`) from `docker-compose.yml` / `.env` (`CATALOG_DRIVER=auto` default). With `PG_HOST` set, `CatalogStore` (`crawler/src/catalog-store.ts:51-60`) writes to Postgres and dual-writes to the `--catalog-db` SQLite file as an offline backup. Set `CATALOG_DRIVER=postgres` for Postgres-only or `CATALOG_DRIVER=sqlite` for SQLite-only. You can also pass a Postgres URL directly: `--catalog-db postgres://user:pass@postgres:5432/job_catalog`.

Outputs:

- Postgres catalog: `job_catalog` database on `postgres:5432` (`postgres_data` volume, schema `init-db.sql`) — primary
- SQLite offline backup: `crawler/state/catalog.sqlite` (`--catalog-db`, maintained via dual-write when `CATALOG_DRIVER=auto`)
- Jobs JSONL snapshot: `crawler/output/current-jobs.jsonl` (`--catalog-file`)
- Report: `crawler/output/report.json`

`exclude.jsonl` is updated automatically after a successful crawl run. Sources that return permanent `404`/`410` failures are appended to the quarantine file and skipped on later runs.

Complete parameter list:

```text
--sources <dir>          Source JSON directory (default: /data/sources)
--providers <list|all>   Providers to crawl (default: all)
--concurrency <n>        Global source concurrency (default: 50)
--out <file>             JSONL output path (default: /app/output/jobs.jsonl)
--report <file>          Report JSON path (default: /app/output/report.json)
--catalog-db <file|url>  Catalog store: SQLite file path (offline backup) or postgres:// URL (default: /app/state/catalog.sqlite; with PG_HOST set, Postgres is primary and SQLite is backup when CATALOG_DRIVER=auto)
--catalog-file <file>    Persistent current-jobs catalog JSONL snapshot (exported from Postgres when available)
--exclude-sources <file> JSONL source quarantine file
--sample <n>             Crawl only first n sources per provider
--max-jobs-per-source <n> Emit at most n jobs per source
--max-age-hours <n>      Keep only jobs where updated_at is within last n hours
--progress-every-ms <n>  Progress log interval, 0 disables it (default: 10000)
--provider-concurrency <spec> Per-provider limits, e.g. ashby=2,workday=10 (default: ashby=2)
--timeout-ms <n>         Per-request timeout (default: 15000)
--retries <n>            Transient retry count (default: 2)
```

Postgres env (see `.env.example`, `docker-compose.yml:128-145`):

```text
CATALOG_DRIVER=auto   # auto | postgres | sqlite
PG_HOST=postgres
PG_PORT=5432
PG_DB=job_catalog
PG_USER=job_admin
PG_PASSWORD=job_admin_password
# DATABASE_URL=postgres://job_admin:job_admin_password@postgres:5432/job_catalog
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

The default quick-fit and full-fit pipelines use `google/gemma-4-e2b` via `http://127.0.0.1:1235` (`NVIDIA_BASE_URL`, see `.env` / `docker-compose.yml`). `job_fit_analyzer.py` is the quick-fit pipeline and `matcher/ensemble_runner.py` is the full-fit pipeline (ensemble scorers/synthesizer both default to `google/gemma-4-e2b`).

`CAREER_OPS_DIR` is configured in `.env` and `.env.example`, so each user can choose their own local folder name under `matcher/`. Those generated profile files are intentionally not tracked in Git.

### 5. Start the local viewer

```bash
docker compose up viewer
```

Open `http://localhost:3000`.

The viewer reads from Postgres primary (`PG_HOST`) with automatic fallback to the SQLite backup at `CATALOG_DB` when `CATALOG_DRIVER=auto` (`viewer/src/db.ts:12-24`). It can trigger quick-fit and full-fit analysis runs directly from the UI, inspect parsed JD data for a job, and reuse saved searches from `viewer/public/saved-searches.json`.

### 6. Run the crawler on a schedule

```bash
docker compose up -d scheduler
```

The `scheduler` service runs the crawler on a daytime schedule and avoids rerunning if the most recent run was too recent. It uses the same crawler defaults shown above (Postgres primary via `docker-compose.yml` env, plus `--exclude-sources` / `--catalog-db` backup / `--catalog-file`).

## Tech Stack

- TypeScript + Node.js for the crawler and viewer
- Python 3.12 for parsing and fit analysis
- Postgres 16 (primary) + SQLite (offline backup/fallback) for the local job catalog
- Docker Compose for local orchestration
- `google/gemma-4-e2b` at `http://127.0.0.1:1235` (OpenAI-compatible `NVIDIA_BASE_URL`) for fit-analysis inference
- Public ATS APIs and page metadata from Greenhouse, Lever, Ashby, BambooHR, Teamtailor, Workday, and Workable

## Module Docs

- [crawler/README.md](crawler/README.md)
- [matcher/README.md](matcher/README.md)
- [viewer/README.md](viewer/README.md)

## Let's Connect

[![LinkedIn](https://img.shields.io/badge/LinkedIn-Michael%20Levy-0A66C2?style=for-the-badge&logo=linkedin&logoColor=white)](https://www.linkedin.com/in/michael-levy-product/)
