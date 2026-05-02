# crawler/state

This directory holds local crawler state and runtime artifacts.

Files:

- `catalog.sqlite`: persistent job catalog used by the crawler and viewer.
- `crawler-progress.json`: progress snapshot written by the crawler run loop.
- `exclude.jsonl`: source quarantine list for known-broken or intentionally skipped sources.
- `hidden-jobs.json`: jobs hidden from the viewer UI.
- `job-analysis-cache.json`: cached job analysis data used by the viewer.
- `scheduler-runs.json`: recent scheduler run timestamps used to throttle cron runs.
- `score-notifications.json`: record of which high-score jobs have already triggered notifications.
- `crawler-active.lock`: guard file used to prevent concurrent crawler runs.
- `match-runs/`: per-match execution outputs, logs, and manifests.

Generated artifacts that may appear temporarily but should not be kept:

- `catalog.sqlite-shm` and `catalog.sqlite-wal`: SQLite sidecar files.
- One-off benchmark or review outputs.
- Archived experiment databases.

The repository intentionally ignores this directory except for this README, so local state does not end up in commits.
