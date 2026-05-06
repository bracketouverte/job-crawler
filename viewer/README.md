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
- `SAVED_SEARCHES_PATH`
- `CRAWLER_ACTIVE_LOCK_PATH`
- `CRAWLER_ACTIVE_LOCK_STALE_MS`

## API Endpoints

- `GET /api/jobs` — supports filtering by title, location, company, provider, age, and salary range
- `GET /api/job`
- `GET /api/sources`
- `GET /api/stats`
- `GET /api/config`
- `POST /api/match-runs`
- `GET /api/match-runs/:id`
- `GET /api/match-runs/:id/results`
- `GET /api/job-parsed`
- `GET /api/logo-dev/brand`

## Discord Notifications

Automatically sends Discord embeds when job matches score above the threshold. Each notification includes job title (linked), company logo thumbnail, score, location, mode, compensation, decision emoji, and company website link.

**Setup**: Create a Discord webhook, add `DISCORD_WEBHOOK_URL` to `.env`, set `SCORE_NOTIFY_MIN_SCORE` threshold (default `4`).

**Decision emojis**: ✅ 4.0–4.2 | ⚡ 4.2–4.5 | 🎯 4.5–4.75 | 🌟 4.75+

## UI Features

- saved-search buttons loaded from `public/saved-searches.json`
- favorite-company filtering stored in local browser storage
- evaluated-only filtering using the local analysis cache
- salary range filtering (min/max) with optional "hide jobs without salary" toggle
- salary badges displayed on job cards (e.g. `$80k–$120k`)
- salary information shown in job detail panels
- quick-fit analysis with the Maverick pipeline
- full-fit analysis with the ensemble pipeline
- JD data modal backed by the parser API
- side-panel fit details and rerun controls
- idle full-fit analysis for saved-search matches, one job at a time, newest first, skipped while the crawler lock is active
