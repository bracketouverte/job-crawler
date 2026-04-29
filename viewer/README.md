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
- `CAREER_OPS_DIR`
- `NVIDIA_API_KEY`
- `NVIDIA_MODEL`

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

## UI Features

- saved-search buttons loaded from `public/saved-searches.json`
- favorite-company filtering stored in local browser storage
- evaluated-only filtering using the local analysis cache
- quick-fit analysis with the Maverick pipeline
- full-fit analysis with the ensemble pipeline
- JD data modal backed by the parser API
- side-panel fit details and rerun controls
