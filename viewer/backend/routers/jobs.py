import json
from pathlib import Path
from typing import Any

import aiofiles
from fastapi import APIRouter, HTTPException

import config
from db import fetchall, fetchone
from services.analysis import best_analysis, get_analysis_cache
from services.company import sanitize_job
from services.filters import ORDER_BY_CLAUSE, add_job_filter_conditions

router = APIRouter(prefix="/api")

JOB_COLUMNS = (
    "provider, source_key, job_id, title, location, employment_type, "
    "compensation, department, job_url, updated_at, posted_at, first_seen_at, "
    "last_seen_at, skill_tier, employment_type_canonical, lat, lon"
)
JOB_DETAIL_COLUMNS = (
    "provider, source_key, job_id, title, location, employment_type, "
    "compensation, department, job_url, updated_at, posted_at, first_seen_at, "
    "last_seen_at, parsed_jd"
)


def _job_cache_key(job: dict) -> str:
    return f"{job['provider']}|{job['source_key']}|{job['job_id']}"


def _enrich(job: dict, cache: dict) -> dict:
    cached = cache.get(_job_cache_key(job))
    sanitized = sanitize_job(job)
    sanitized["analysis"] = best_analysis(cached)
    sanitized["pipelines"] = (cached or {}).get("pipelines", {})
    return sanitized


def _require_job_key(provider: str | None, source_key: str | None, job_id: str | None) -> None:
    if not provider or not source_key or not job_id:
        raise HTTPException(status_code=400, detail="provider, source_key, and job_id are required")


@router.get("/jobs")
async def list_jobs(
    title: str | None = None,
    myLoc: str | None = None,
    remote: str | None = None,
    days: str | None = None,
    company: str | None = None,
    sources: str | None = None,
    page: int = 1,
    limit: int = 50,
    favCompanies: str | None = None,
    evaluated: str | None = None,
    score: str | None = None,
    inc: str | None = None,
    exc: str | None = None,
    tiers: str | None = None,
    types: str | None = None,
) -> dict:
    page_num = max(1, page)
    page_size = min(500, max(1, limit))
    offset = (page_num - 1) * page_size

    include_remote = remote != "0"
    fav_list = [c.strip() for c in favCompanies.split(",") if c.strip()] if favCompanies else None
    evaluated_flag = evaluated == "1"

    where, params = add_job_filter_conditions(
        title=title,
        my_location=myLoc,
        include_remote=include_remote,
        company=company,
        sources=sources,
        days=days,
        fav_companies=fav_list,
        include=inc,
        exclude=exc,
        tiers=tiers,
        types=types,
        evaluated=evaluated_flag,
        score=score,
    )

    total_row = await fetchone(f"SELECT COUNT(*) AS n FROM catalog_jobs {where}", params)
    total = total_row["n"] if total_row else 0

    rows = await fetchall(
        f"SELECT {JOB_COLUMNS} FROM catalog_jobs {where} {ORDER_BY_CLAUSE} LIMIT ? OFFSET ?",
        [*params, page_size, offset],
    )

    cache = await get_analysis_cache()
    jobs = [_enrich(row, cache) for row in rows]

    return {"jobs": jobs, "total": total, "page": page_num, "limit": page_size}


@router.get("/job")
async def get_job(
    provider: str | None = None, source_key: str | None = None, job_id: str | None = None
) -> dict:
    _require_job_key(provider, source_key, job_id)

    row = await fetchone(
        f"SELECT {JOB_DETAIL_COLUMNS} FROM catalog_jobs WHERE provider = ? AND source_key = ? AND job_id = ?",
        (provider, source_key, job_id),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")

    cache = await get_analysis_cache()
    return _enrich(row, cache)


@router.get("/job-parsed")
async def get_job_parsed(
    provider: str | None = None, source_key: str | None = None, job_id: str | None = None
) -> Any:
    _require_job_key(provider, source_key, job_id)

    row = await fetchone(
        "SELECT parsed_jd FROM catalog_jobs WHERE provider = ? AND source_key = ? AND job_id = ?",
        (provider, source_key, job_id),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not row["parsed_jd"]:
        raise HTTPException(status_code=404, detail="Not yet parsed — run analysis first")

    try:
        return json.loads(row["parsed_jd"])
    except (TypeError, ValueError):
        raise HTTPException(status_code=500, detail="Corrupted parse cache")


@router.get("/sources")
async def list_sources() -> dict:
    rows = await fetchall("SELECT DISTINCT provider FROM catalog_jobs ORDER BY provider")
    return {"sources": [row["provider"] for row in rows]}


@router.get("/stats")
async def get_stats() -> dict:
    by_provider = await fetchall(
        "SELECT provider, COUNT(*) AS count FROM catalog_jobs GROUP BY provider ORDER BY count DESC"
    )
    total = sum(row["count"] for row in by_provider)
    last_row = await fetchone("SELECT MAX(last_seen_at) AS ts FROM catalog_jobs")
    last_crawl = last_row["ts"] if last_row else None
    return {"total": total, "byProvider": by_provider, "lastCrawl": last_crawl}


@router.get("/trends")
async def get_trends() -> list:
    path = Path(config.STATE_DIR) / "trends.jsonl"
    try:
        async with aiofiles.open(path, encoding="utf-8") as f:
            raw = await f.read()
    except OSError:
        return []

    lines = [line for line in raw.strip().split("\n") if line]
    trends = []
    for line in lines[-30:]:
        try:
            trends.append(json.loads(line))
        except ValueError:
            continue
    return trends
