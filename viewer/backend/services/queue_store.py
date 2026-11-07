import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiofiles

import config

_LOCK = asyncio.Lock()


def queue_path() -> Path:
    return Path(config.STATE_DIR) / "retry-queue.json"


async def read_queue() -> list[dict]:
    try:
        async with aiofiles.open(queue_path(), encoding="utf-8") as f:
            raw = await f.read()
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


async def _write_queue_unlocked(items: list[dict]) -> None:
    path = queue_path()
    tmp_path = path.with_name(f".{path.name}.tmp")
    async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
        await f.write(json.dumps(items, indent=2) + "\n")
    os.replace(tmp_path, path)


async def write_queue(items: list[dict]) -> None:
    async with _LOCK:
        await _write_queue_unlocked(items)


async def upsert_queue_item(item: dict) -> None:
    async with _LOCK:
        items = await read_queue()
        idx = next((i for i, existing in enumerate(items) if existing.get("id") == item["id"]), None)
        if idx is not None:
            items[idx] = item
        else:
            items.append(item)
        await _write_queue_unlocked(items)


async def remove_queue_item(item_id: str) -> None:
    async with _LOCK:
        items = await read_queue()
        items = [i for i in items if i.get("id") != item_id]
        await _write_queue_unlocked(items)


def run_id_from_item_id(item_id: str) -> str:
    idx = item_id.find(":")
    return item_id if idx == -1 else item_id[:idx]


def build_subtasks(mode: str) -> list[dict]:
    """Coarse parse/score/discord subtasks.

    Per-scorer progress (maverick/kimi/nemotron/synthesis) used to be derived
    by parsing subprocess log lines in real time; now that scoring happens
    via a single synchronous HTTP call to the matcher service, that
    granularity isn't observable from the viewer, so the model is
    intentionally simplified to three coarse phases.
    """
    score_label = "Ensemble score" if mode == "claude-ensemble" else "Score"
    return [
        {"id": "parse", "label": "Parse JD", "status": "todo"},
        {"id": "score", "label": score_label, "status": "todo"},
        {"id": "discord", "label": "Discord push", "status": "todo"},
    ]


def retry_backoff_seconds(attempt: int) -> int:
    return 30 * (2**attempt)


def next_retry_at(attempt: int) -> str:
    delay = timedelta(seconds=retry_backoff_seconds(attempt))
    return (datetime.now(UTC) + delay).isoformat().replace("+00:00", "Z")
