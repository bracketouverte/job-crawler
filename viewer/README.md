# Viewer

`viewer` is a FastAPI backend (`backend/`) + React/TypeScript frontend (`frontend/`) that reads the
crawler's SQLite catalog and exposes:

- a browser UI for filtering, favorites, saved searches, the analysis queue, and JD inspection
- JSON APIs for jobs, sources, stats, match runs, and the retry queue
- subprocess orchestration of the local matcher scripts for quick-fit and full-fit analysis

In production it's a single Docker image (`viewer/Dockerfile`): the frontend is built and its
`dist/` output is baked into the FastAPI image's static file mount, so one process serves both the
UI and the API.

## Local development

Backend and frontend run as two separate processes in dev (Vite proxies `/api/*` to FastAPI so
there's no CORS to deal with).

**Backend:**

```bash
cd viewer/backend
pip install -r requirements.txt -r requirements-dev.txt
uvicorn main:app --reload --port 3000
```

**Frontend** (separate terminal):

```bash
cd viewer/frontend
npm install
npm run dev
```

Open `http://localhost:5173`. If your backend isn't on `localhost:3000`, point the dev proxy
elsewhere with `VITE_BACKEND_URL` (see `vite.config.ts`).

Per this repo's Docker-only policy, prefer the `justfile` at the repo root instead of running
`pip`/`npm` on the host directly:

```bash
just dev    # backend, uvicorn --reload, Docker-backed
just lint   # ruff + black --check
just test   # pytest with coverage (70% gate)
just fmt    # ruff --fix + black
```

`just dev` currently covers the backend only; run the frontend commands above directly (they're
already sandboxed inside `node:20-slim` via Docker if you'd rather not install Node locally — see
the `docker run -v ... node:20-slim npm run dev` pattern used in this repo's CI/verification steps).

**`saved-searches.json` must exist at `viewer/frontend/public/saved-searches.json`** — both the
frontend (served as a static asset) and the backend's saved-search auto-analyzer read this same
file. Without it, saved-search chips won't render and the idle analyzer has nothing to do.

## Docker (production)

```bash
docker compose build viewer && docker compose up -d viewer
```

Open `http://localhost:3000`. The image runs `uvicorn --workers 1` — hardcoded, not configurable —
because in-memory state (`active_run_ids`, the analysis/logo-dev caches) is process-local and
breaks under multiple workers.

## What it reads

- catalog: `CATALOG_DB` (default `/app/state/catalog.sqlite`; mounted from `crawler/state/` in
  `docker-compose.yml`)
- matcher scripts: `MATCHER_DIR` (default `/matcher`, mounted read-only)

The viewer needs access to the matcher codebase because it shells out to `job_post_parser.py`,
`job_fit_analyzer.py`, and `ensemble_runner.py` to parse job posts and run fit analysis.

## Environment

| Var | Notes |
|---|---|
| `CATALOG_DB`, `STATE_DIR`, `MATCH_RUNS_DIR`, `ANALYSIS_CACHE_PATH` | paths, derived from `STATE_DIR` by default |
| `HIDDEN_JOBS_PATH`, `SCORE_NOTIFICATIONS_PATH`, `CRAWLER_ACTIVE_LOCK_PATH`, `CRAWLER_PROGRESS_PATH` | more `STATE_DIR`-derived paths |
| `SAVED_SEARCHES_PATH` | default assumes a `backend/`+`frontend/` sibling layout — **override to `/app/static/saved-searches.json` in the production image**, since only `frontend/dist` is copied there |
| `STATIC_DIR` | same story — default assumes the dev sibling layout; **override to `/app/static` in production** |
| `MATCHER_DIR`, `PYTHON_BIN`, `CAREER_OPS_DIR` | matcher subprocess config |
| `LOGO_DEV_PUBLISHABLE_KEY`, `LOGO_DEV_SECRET_KEY` | logo.dev company logos + brand search |
| `DISCORD_WEBHOOK_URL`, `SCORE_NOTIFY_MIN_SCORE` (default `4`) | score-threshold Discord notifications |
| `NVIDIA_API_KEY`, `NVIDIA_MODEL`, `NVIDIA_ENSEMBLE_SCORERS`, `NVIDIA_ENSEMBLE_SYNTHESIZER` | passed through to matcher subprocesses |
| `SAVED_SEARCH_ANALYZER_ENABLED` (`0` disables), `SAVED_SEARCH_ANALYZER_INTERVAL_MS` (default `60000`) | idle saved-search full analyzer |
| `CRAWLER_ACTIVE_LOCK_STALE_MS` (default `7200000`) | how long the crawler lock file is trusted before being treated as stale |
| `USER_LOCATION` | shown in `/api/config` |
| `PORT` (default `3000`) | not read by uvicorn directly — see the Dockerfile's hardcoded `--port 3000` |

`docker-compose.yml`'s `viewer` service sets the production-only overrides (`STATIC_DIR`,
`SAVED_SEARCHES_PATH`) explicitly; everything else has a sane default.

## API endpoints

Jobs: `GET /api/jobs`, `GET /api/job`, `GET /api/job-parsed`, `GET /api/sources`, `GET /api/stats`,
`GET /api/trends`.

Match runs: `POST /api/match-runs`, `POST /api/match-runs-with-jd`, `GET /api/match-runs/{id}`,
`GET /api/match-runs/{id}/results`.

Queue: `GET /api/queue`, `POST /api/queue/{id}/retry`, `POST /api/queue/{id}/stop`,
`POST /api/queue/{id}/restart`, `DELETE /api/queue/{id}`.

Auto-analyzer: `GET /api/auto-analyzer`, `POST /api/auto-analyzer`.

Everything else: `GET /api/config`, `GET /api/crawl-status`, `GET /api/hidden-jobs`,
`PUT /api/hidden-jobs`, `GET /api/logo-dev/brand`.

## Discord notifications

Sends a Discord embed when a job's ensemble/quick score clears `SCORE_NOTIFY_MIN_SCORE`, deduped so
a re-analysis only re-notifies on a *higher* score. Each embed has the job title (linked), company
logo thumbnail, score, location, work mode, compensation, decision emoji, and company website link.
On webhook failure, a `discord-only` retry-queue item is enqueued and picked up by the retry
scheduler.

**Decision emojis**: ✅ 4.0–4.2 · ⚡ 4.2–4.5 · 🎯 4.5–4.75 · 🌟 4.75+

## UI features

- saved-search chips loaded from `frontend/public/saved-searches.json`
- favorite companies and hidden/visited jobs, persisted to `localStorage`
- quick-fit analysis (single model) and full-fit analysis (ensemble)
- analysis side panel with per-pipeline tabs, scorecard, tool-match pills, gaps/blockers, and a
  lazy-loaded JD accordion
- queue drawer with live subtask progress, a "To Apply" bucket, and retry/stop/restart/dismiss
- idle full-fit analysis for saved-search matches, one job at a time, newest first, skipped while
  the crawler lock is active
