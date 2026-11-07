import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

import aiofiles

import config
from db import fetchall
from services import queue_store
from services.analysis import get_analysis_cache, has_full_analysis
from services.filters import add_job_filter_conditions
from services.match_run import (
    STATUS_PENDING,
    active_run_ids,
    execute_match_run,
    generate_run_id,
    write_manifest,
)
from services.notifications import read_hidden_jobs

logger = logging.getLogger(__name__)

JOB_COLUMNS = (
    "provider, source_key, job_id, title, location, employment_type, "
    "compensation, department, job_url, updated_at, posted_at, first_seen_at, last_seen_at"
)
_BATCH_SIZE = 200
_STARTUP_DELAY_S = 5

saved_search_analyzer_paused = False
saved_search_analyzer_busy = False
saved_search_analyzer_current: dict | None = None

_task: asyncio.Task | None = None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def set_paused(value: bool) -> None:
    global saved_search_analyzer_paused
    saved_search_analyzer_paused = value


async def read_saved_searches() -> list[dict]:
    try:
        async with aiofiles.open(config.SAVED_SEARCHES_PATH, encoding="utf-8") as f:
            raw = await f.read()
        parsed = json.loads(raw)
        return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []
    except (OSError, ValueError) as exc:
        logger.error("saved-search analyzer: failed to read saved searches: %s", exc)
        return []


async def is_crawler_active() -> bool:
    try:
        mtime = Path(config.CRAWLER_ACTIVE_LOCK_PATH).stat().st_mtime
    except OSError:
        return False
    return (time.time() - mtime) * 1000 <= config.CRAWLER_ACTIVE_LOCK_STALE_MS


async def find_next_saved_search_job() -> dict | None:
    searches = await read_saved_searches()
    if not searches:
        return None

    analysis_cache = await get_analysis_cache()
    hidden_jobs = await read_hidden_jobs()

    queue_items = await queue_store.read_queue()
    active_queue_keys = {
        item["job_key"] for item in queue_items if item.get("status") in ("running", "todo", "retrying")
    }

    for search in searches:
        where, params = add_job_filter_conditions(
            title=search.get("title"),
            my_location=search.get("location"),
            include_remote=True,
            company=search.get("company"),
            sources=search.get("sources"),
            days=search.get("days"),
        )
        where = f"{where} AND job_url IS NOT NULL" if where else "WHERE job_url IS NOT NULL"

        offset = 0
        while True:
            jobs = await fetchall(
                f"SELECT {JOB_COLUMNS} FROM catalog_jobs {where} "
                "ORDER BY COALESCE(posted_at, first_seen_at) DESC LIMIT ? OFFSET ?",
                [*params, _BATCH_SIZE, offset],
            )
            if not jobs:
                break

            for job in jobs:
                key = f"{job['provider']}|{job['source_key']}|{job['job_id']}"
                if (
                    key in hidden_jobs
                    or has_full_analysis(analysis_cache.get(key))
                    or key in active_queue_keys
                ):
                    continue
                return {"job": job, "search": search}

            offset += _BATCH_SIZE

    return None


async def run_saved_search_analyzer_once() -> None:
    global saved_search_analyzer_busy, saved_search_analyzer_current

    if not config.SAVED_SEARCH_ANALYZER_ENABLED or saved_search_analyzer_paused or saved_search_analyzer_busy:
        return
    if active_run_ids:
        return
    if await is_crawler_active():
        return

    saved_search_analyzer_busy = True
    try:
        next_job = await find_next_saved_search_job()
        if next_job is None:
            return

        job = next_job["job"]
        search = next_job["search"]
        job_key = f"{job['provider']}|{job['source_key']}|{job['job_id']}"

        run_id = generate_run_id()
        now = _now_iso()
        manifest = {
            "id": run_id,
            "status": STATUS_PENDING,
            "mode": "claude-ensemble",
            "job_count": 1,
            "parsed_count": 0,
            "matched_count": 0,
            "created_at": now,
            "updated_at": now,
            "error": None,
        }

        logger.info(
            "saved-search analyzer: full analysis start | search=%s | job=%s",
            search.get("id") or search.get("label") or "saved-search",
            job_key,
        )
        await write_manifest(run_id, manifest)
        saved_search_analyzer_current = {
            "run_id": run_id,
            "job_key": job_key,
            "search_id": search.get("id"),
            "search_label": search.get("label"),
            "started_at": now,
        }
        await execute_match_run(run_id, [job], "claude-ensemble")
    except Exception:
        logger.exception("saved-search analyzer error")
    finally:
        saved_search_analyzer_current = None
        saved_search_analyzer_busy = False


async def _loop() -> None:
    await asyncio.sleep(_STARTUP_DELAY_S)
    while True:
        try:
            await run_saved_search_analyzer_once()
        except Exception:
            logger.exception("saved-search analyzer: unhandled loop error")
        await asyncio.sleep(config.SAVED_SEARCH_ANALYZER_INTERVAL_MS / 1000)


def start() -> asyncio.Task:
    global _task
    _task = asyncio.create_task(_loop())
    return _task


async def stop() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
