import json
import os
from datetime import UTC, datetime, timedelta

import config


def read_runs() -> list[str]:
    try:
        with open(config.RUNS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def record_run(ts: str) -> None:
    runs = read_runs()
    runs.append(ts)
    runs = runs[-config.MAX_RUNS_HISTORY :]

    path = config.RUNS_FILE
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(runs, f)
    os.replace(tmp_path, path)


def last_run_at() -> datetime | None:
    runs = read_runs()
    if not runs:
        return None
    try:
        return datetime.strptime(runs[-1], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def is_debounced() -> bool:
    last = last_run_at()
    if last is None:
        return False
    return datetime.now(UTC) - last < timedelta(minutes=config.DEBOUNCE_MINUTES)
