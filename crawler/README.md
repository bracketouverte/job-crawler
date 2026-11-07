# Job Scrapper Crawler

Standalone Dockerized crawler for public ATS job boards.

## Quick Start

Run with catalog persistence (SQLite + JSONL output):

```bash
docker compose run --rm crawler \
  --concurrency 8 \
  --provider-concurrency ashby=1,workday=4,lever=3,teamtailor=2,bamboohr=3,greenhouse=6,workable=2,smartrecruiters=2,icims=5 \
  --timeout-ms 30000 \
  --retries 5 \
  --exclude-sources /app/state/exclude.jsonl \
  --catalog-db /app/state/catalog.sqlite
```

Outputs:
- SQLite catalog: `crawler/state/catalog.sqlite`
- Jobs JSONL: `crawler/output/jobs.jsonl`
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

- `--max-age-hours` filters on normalized `updated_at`. Jobs with missing or invalid `updated_at` are excluded when this flag is set. This filtering applies only to `--out`'s JSONL export -- `--catalog-db` always keeps every job, so `last_seen_at` stays current regardless of age.
- `--catalog-db` keeps the persistent SQLite state that powers the current-jobs catalog.

## Run Modes

Use parameter presets to tune stability vs speed:

### Safe Mode (Recommended)

Best for stability. Use when hitting rate limits or 403/429 errors.

```bash
docker compose run --rm crawler \
  --concurrency 8 \
  --provider-concurrency ashby=1,workday=4,lever=3,teamtailor=2,bamboohr=3,greenhouse=6,workable=2,smartrecruiters=2,icims=5 \
  --timeout-ms 30000 \
  --retries 5 \
  --exclude-sources /app/state/exclude.jsonl \
  --catalog-db /app/state/catalog.sqlite
```

To skip known-broken sources (404s/410s), add `--exclude-sources /app/state/exclude.jsonl`. The post-crawl hook automatically updates this file with new failures after each run.

### Balanced Mode

Compromise between runtime and stability.

```bash
docker compose run --rm crawler \
  --concurrency 20 \
  --provider-concurrency ashby=2,workday=15,lever=15,icims=8 \
  --timeout-ms 20000 \
  --retries 3 \
  --catalog-db /app/state/catalog.sqlite
```

### Aggressive Mode

Fastest runtime but higher refusal/rate-limit risk.

```bash
docker compose run --rm crawler \
  --concurrency 50 \
  --provider-concurrency ashby=2,icims=10 \
  --timeout-ms 15000 \
  --retries 2 \
  --catalog-db /app/state/catalog.sqlite
```

## Output Files

Default output directory: `crawler/output/`

- `jobs.jsonl` — Jobs from latest run (deduped, filtered by `--max-age-hours` if set)
- `report.json` — Statistics and failures summary

The repository ignores all local artifacts (only `.gitkeep` is tracked).

## Source Quarantine (Optional)

Skip broken sources using an exclusion file:

```bash
docker compose run --rm crawler \
  --exclude-sources /app/state/exclude.jsonl \
  --catalog-db /app/state/catalog.sqlite
```

The exclusion file is a JSONL of sources that returned 404 or permanent errors in previous runs.
This prevents re-crawling known-broken sources.
After each successful run, the post-crawl hook (now run in-process by `main.py`, no longer a separate shell step) automatically appends new `404`/`410` failures to `crawler/state/exclude.jsonl`.

## Provider Notes

### iCIMS
- **Mechanism**: XML sitemap at `https://careers-{slug}.icims.com/sitemap.xml`
- **Data available**: title (reconstructed from URL slug), job URL, job ID
- **Not available**: location, employment type, compensation, posted date — the sitemap does not expose these fields. Fetching individual job pages would provide them but is too costly at ~10k sources.
- **Rate limit posture**: conservative — max 5–10 concurrent requests. iCIMS has no published rate limits but blocks aggressively. Dead slugs accumulate fast (~40% of the 9,937 listed companies are inactive); the exclude file eliminates the overhead on subsequent runs.
- **Source file**: `sources/icims.json` — 9,937 slugs from Common Crawl harvesting (same list as job-board-aggregator).

## Scheduler Service

From the repo root:

```bash
docker compose up -d scheduler
```

The scheduler service runs the crawler during the configured daytime window and skips runs that would happen too close together. It writes its last-run state under `crawler/state/` and uses the same crawler defaults as the compose-managed crawler service.
