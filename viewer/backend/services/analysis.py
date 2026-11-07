import asyncio
import json
import logging
import math
import time
from datetime import UTC, datetime
from pathlib import Path

import aiofiles

import config
from db import execute, executemany, fetchall

logger = logging.getLogger(__name__)

_CACHE_TTL_S = 5.0
_cache: dict | None = None
_cache_at: float = 0.0
_migrated = False


def parse_job_key(key: str) -> tuple[str, str, str] | None:
    parts = key.split("|")
    if len(parts) < 3:
        return None
    provider, source_key, *rest = parts
    return provider, source_key, "|".join(rest)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def analysis_score_5(analysis: object) -> float | None:
    if not isinstance(analysis, dict):
        return None
    value = analysis.get("score_5")
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return score if math.isfinite(score) else None


async def _write_score_to_job_row(job_key: str, analysis: object) -> None:
    score = analysis_score_5(analysis)
    if score is None:
        return
    parsed = parse_job_key(job_key)
    if parsed is None:
        return
    provider, source_key, job_id = parsed
    try:
        await execute(
            "UPDATE catalog_jobs SET analysis_score = ? "
            "WHERE provider = ? AND source_key = ? AND job_id = ?",
            (score, provider, source_key, job_id),
        )
    except Exception:
        pass  # catalog_jobs row may not exist (e.g. test data)


def _rows_to_cache(rows: list[dict]) -> dict:
    cache: dict = {}
    for row in rows:
        try:
            analysis = json.loads(row["analysis"])
        except (TypeError, ValueError):
            analysis = None
        entry = cache.setdefault(row["job_key"], {"pipelines": {}})
        entry["pipelines"][row["pipeline"]] = {
            "analysis": analysis,
            "analyzed_at": row["analyzed_at"],
            "run_id": row["run_id"],
        }
    return cache


async def _migrate_legacy_cache_if_empty() -> None:
    existing = await fetchall("SELECT 1 FROM job_analyses LIMIT 1")
    if existing:
        return

    path = Path(config.ANALYSIS_CACHE_PATH)
    try:
        async with aiofiles.open(path, encoding="utf-8") as f:
            raw = await f.read()
        parsed = json.loads(raw)
    except (OSError, ValueError):
        return

    if not isinstance(parsed, dict):
        return

    rows = []
    for job_key, cached in parsed.items():
        if not isinstance(cached, dict):
            continue
        pipelines = cached.get("pipelines") or {}
        for pipeline, entry in pipelines.items():
            rows.append(
                (
                    job_key,
                    pipeline,
                    json.dumps(entry.get("analysis")),
                    entry.get("analyzed_at") or _now_iso(),
                    entry.get("run_id") or "",
                )
            )
        if not pipelines and cached.get("analysis") is not None:
            rows.append(
                (
                    job_key,
                    "legacy",
                    json.dumps(cached.get("analysis")),
                    cached.get("analyzed_at") or _now_iso(),
                    cached.get("run_id") or "",
                )
            )

    if rows:
        await executemany(
            "INSERT OR IGNORE INTO job_analyses "
            "(job_key, pipeline, analysis, analyzed_at, run_id) VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        logger.info("migrated JSON cache -> SQLite (%d keys)", len(parsed))


def invalidate_analysis_cache() -> None:
    global _cache, _cache_at
    _cache = None
    _cache_at = 0.0


async def get_analysis_cache() -> dict:
    global _cache, _cache_at, _migrated

    if not _migrated:
        await _migrate_legacy_cache_if_empty()
        _migrated = True

    now = time.monotonic()
    if _cache is not None and (now - _cache_at) < _CACHE_TTL_S:
        return _cache

    rows = await fetchall("SELECT job_key, pipeline, analysis, analyzed_at, run_id FROM job_analyses")
    _cache = _rows_to_cache(rows)
    _cache_at = now
    return _cache


def best_analysis(cached_entry: dict | None) -> object | None:
    if not cached_entry:
        return None
    pipelines = cached_entry.get("pipelines") or {}
    if pipelines.get("claude-ensemble"):
        return pipelines["claude-ensemble"]["analysis"]
    if pipelines.get("claude"):
        return pipelines["claude"]["analysis"]
    entries = list(pipelines.values())
    if not entries:
        return cached_entry.get("analysis")
    entries.sort(key=lambda e: e.get("analyzed_at") or "", reverse=True)
    return entries[0]["analysis"]


def has_full_analysis(cached_entry: dict | None) -> bool:
    if not cached_entry:
        return False
    return (cached_entry.get("pipelines") or {}).get("claude-ensemble") is not None


_UPSERT_SQL = (
    "INSERT INTO job_analyses (job_key, pipeline, analysis, analyzed_at, run_id) "
    "VALUES (?, ?, ?, ?, ?) "
    "ON CONFLICT(job_key, pipeline) DO UPDATE SET "
    "analysis = excluded.analysis, analyzed_at = excluded.analyzed_at, run_id = excluded.run_id"
)


async def upsert_analysis(job_key: str, pipeline: str, analysis_obj: object, run_id: str) -> None:
    await execute(
        _UPSERT_SQL,
        (job_key, pipeline, json.dumps(analysis_obj), _now_iso(), run_id),
    )
    await _write_score_to_job_row(job_key, analysis_obj)
    invalidate_analysis_cache()


async def persist_run_results(results: list[dict], run_id: str, notify_fn=None) -> None:
    analyzed_at = _now_iso()
    batch: list[tuple] = []
    ok_rows: list[dict] = []

    for row in results:
        if row.get("status") != "ok":
            continue
        provider = row.get("provider")
        source_key = row.get("source_key")
        job_id = row.get("job_id")
        if not (isinstance(provider, str) and isinstance(source_key, str) and isinstance(job_id, str)):
            continue
        job_key = f"{provider}|{source_key}|{job_id}"
        analysis_obj = row.get("analysis")
        pipeline_tag = str((analysis_obj or {}).get("pipeline") or "maverick")
        batch.append((job_key, pipeline_tag, json.dumps(analysis_obj), analyzed_at, run_id))
        ok_rows.append(row)

    if batch:
        await executemany(_UPSERT_SQL, batch)
        for (job_key, *_rest), row in zip(batch, ok_rows):
            await _write_score_to_job_row(job_key, row.get("analysis"))

    invalidate_analysis_cache()

    if ok_rows and notify_fn is not None:
        notif_tasks = [notify_fn(row, run_id) for row in ok_rows]
        await asyncio.gather(*notif_tasks, return_exceptions=True)
