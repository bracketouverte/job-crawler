# Job Scrapper Crawler

Standalone Dockerized crawler for public ATS job boards.

## Quick Start

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

## CLI Options

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

Notes:

- `--max-age-hours` filters on normalized `updated_at`. Jobs with missing or invalid `updated_at` are excluded when this flag is set.
- `--catalog-db` keeps the persistent SQLite state that powers the current-jobs catalog.
- `--catalog-file` exports the latest catalog snapshot after the run.

## Run Modes

Use parameter presets to tune stability vs speed:

### Safe Mode (Recommended)

Best for stability. Use when hitting rate limits or 403/429 errors.

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

To skip known-broken sources (404s/410s), add `--exclude-sources /app/state/exclude.jsonl`. The post-crawl hook automatically updates this file with new failures after each run.

### Balanced Mode

Compromise between runtime and stability.

```bash
docker compose run --rm crawler \
  --concurrency 20 \
  --provider-concurrency ashby=2,workday=15,lever=15 \
  --timeout-ms 20000 \
  --retries 3 \
  --catalog-db /app/state/catalog.sqlite \
  --catalog-file /app/output/current-jobs.jsonl
```

### Aggressive Mode

Fastest runtime but higher refusal/rate-limit risk.

```bash
docker compose run --rm crawler \
  --concurrency 50 \
  --provider-concurrency ashby=2 \
  --timeout-ms 15000 \
  --retries 2 \
  --catalog-db /app/state/catalog.sqlite \
  --catalog-file /app/output/current-jobs.jsonl
```

## Output Files

Default output directory: `crawler/output/`

- `current-jobs.jsonl` — All jobs from latest run
- `report.json` — Statistics and failures summary

The repository ignores all local artifacts (only `.gitkeep` is tracked).

## Source Quarantine (Optional)

Skip broken sources using an exclusion file:

```bash
docker compose run --rm crawler \
  --exclude-sources /app/state/exclude.jsonl \
  --catalog-db /app/state/catalog.sqlite \
  --catalog-file /app/output/current-jobs.jsonl
```

The exclusion file is a JSONL of sources that returned 404 or permanent errors in previous runs.
This prevents re-crawling known-broken sources.
When the crawler runs through the Docker entrypoint, the post-crawl hook automatically appends new `404`/`410` failures to `crawler/state/exclude.jsonl` after a successful run.

## Scheduler Service

From the repo root:

```bash
docker compose up -d scheduler
```

The scheduler service runs the crawler during the configured daytime window and skips runs that would happen too close together. It writes its last-run state under `crawler/state/` and uses the same crawler defaults as the compose-managed crawler service.
