# Viewer

The `viewer` module is a small Express app that reads the crawler SQLite catalog and exposes:

- a static browser UI for filtering, favorites, saved searches, and JD inspection
- JSON APIs for jobs, sources, and stats
- a local matcher-backed quick-fit and full-fit orchestration flow

## What It Reads

- default catalog path: `/app/state/catalog.sqlite`
- local mounted path in this repo: `crawler/state/catalog.sqlite`

## Run

```bash
docker compose up viewer
```

Open `http://localhost:3000`.

The viewer expects access to the matcher codebase because it can parse job URLs and trigger local fit-analysis runs from the UI.

## Environment

- `CATALOG_DB`
- `STATE_DIR`
- `MATCH_RUNS_DIR`
- `ANALYSIS_CACHE_PATH`
- `MATCHER_DIR`
- `PYTHON_BIN`
- `LOGO_DEV_PUBLISHABLE_KEY`
- `LOGO_DEV_SECRET_KEY`
- `DISCORD_WEBHOOK_URL`
- `SCORE_NOTIFY_MIN_SCORE` (default `4`)
- `CAREER_OPS_DIR`
- `NVIDIA_API_KEY`
- `NVIDIA_MODEL`
- `SAVED_SEARCH_ANALYZER_ENABLED` (`0` disables the idle saved-search full analyzer)
- `SAVED_SEARCH_ANALYZER_INTERVAL_MS` (default `60000`)
- `TARGET_TITLES` (comma-separated target titles; when set, the auto-analyzer skips non-matching jobs without an LLM call)
- `TARGET_TITLES_PATH` (default `viewer/public/target-titles.json`; used when `TARGET_TITLES` is empty)
- `TITLE_FILTER_URL` (default `http://title-filter:8001/score`; Laya sidecar — substring fallback when unreachable)
- `TITLE_MATCH_MIN_CONFIDENCE` (default `0.85`; below-threshold Laya results fall back to the LLM)
- `JOB_LOCATION_TYPE` (e.g. `"remote_US, hybrid_US, onsite_US"`; empty disables; unknown work mode is fail-open)
- `JOB_LOCATION_METRO` (e.g. `"chicago, los angeles"`; job location must contain one entry; empty disables)
- `SALARY` (e.g. `"120000"`; job qualifies when the number is inside its salary range; blank disables, unknown salary is fail-open)
- `SAVED_SEARCHES_PATH`
- `CRAWLER_ACTIVE_LOCK_PATH`
- `CRAWLER_ACTIVE_LOCK_STALE_MS`

## API Endpoints

- `GET /api/jobs`
- `GET /api/job`
- `GET /api/sources`
- `GET /api/stats`
- `GET /api/config`
- `POST /api/match-runs`
- `GET /api/match-runs/:id`
- `GET /api/match-runs/:id/results`
- `GET /api/job-parsed`
- `GET /api/logo-dev/brand`
- `GET /api/auto-analyzer`
- `GET /api/title-filter` (effective targets, threshold, sidecar health)

## Title Pre-filter (Laya)

Before the auto-analyzer spends an LLM call, each candidate job is scored by the `title-filter` sidecar ([Laya](https://github.com/NandhaKishorM/laya) English checkpoint, single forward pass) against `TARGET_TITLES` / `target-titles.json`, plus deterministic location/salary gates:

- high-confidence title mismatch, location-type/metro mismatch, or salary out of range → skipped, marker recorded in `job-analysis-cache.json` (`filter_skip`) so the 60s loop doesn't rescan it
- match, low confidence, missing data (fail-open), or sidecar unreachable → falls back to the normal LLM ensemble path

Run the sidecar with `docker compose up -d title-filter` (or it starts with `viewer` via `depends_on`). Check `GET /api/title-filter` for effective config and sidecar health.

## Discord Notifications

Automatically sends Discord embeds when job matches score above the threshold. Each notification includes job title (linked), company logo thumbnail, score, location, mode, compensation, decision emoji, and company website link.

**Setup**: Create a Discord webhook, add `DISCORD_WEBHOOK_URL` to `.env`, set `SCORE_NOTIFY_MIN_SCORE` threshold (default `4`).

**Decision emojis**: ✅ 4.0–4.2 | ⚡ 4.2–4.5 | 🎯 4.5–4.75 | 🌟 4.75+

## UI Features

- saved-search buttons loaded from `public/saved-searches.json`
- favorite-company filtering stored in local browser storage
- evaluated-only filtering using the local analysis cache
- quick-fit analysis with the Maverick pipeline
- full-fit analysis with the ensemble pipeline
- JD data modal backed by the parser API
- side-panel fit details and rerun controls
- idle full-fit analysis for saved-search matches, one job at a time, newest first, skipped while the crawler lock is active
