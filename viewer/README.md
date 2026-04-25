# Viewer

The `viewer` module is a small Express app that reads the crawler SQLite catalog and exposes:

- a static browser UI
- JSON APIs for jobs, sources, and stats

## What It Reads

- default catalog path: `/app/state/catalog.sqlite`
- local mounted path in this repo: `crawler/state/catalog.sqlite`

## Run

```bash
docker compose up viewer
```

Open `http://localhost:3000`.

## Environment

- `CATALOG_DB`
- `LOGO_DEV_PUBLISHABLE_KEY`
- `LOGO_DEV_SECRET_KEY`

## API Endpoints

- `GET /api/jobs`
- `GET /api/sources`
- `GET /api/stats`
