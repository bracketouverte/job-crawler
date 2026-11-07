import asyncio
import json
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import fetchone
from services.analysis import parse_job_key
from services.company import company_name, sanitize_job
from services.match_run import (
    STATUS_PENDING,
    active_run_ids,
    execute_match_run,
    execute_match_run_from_input,
    generate_run_id,
    read_manifest,
    read_results_jsonl,
    write_manifest,
)

router = APIRouter(prefix="/api")


class MatchRunRequest(BaseModel):
    job_keys: list[str]
    mode: str


class MatchRunWithJdRequest(BaseModel):
    provider: str
    source_key: str
    job_id: str
    jd_text: str
    mode: str


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _base_manifest(run_id: str, mode: str, job_count: int) -> dict:
    now = _now_iso()
    return {
        "id": run_id,
        "status": STATUS_PENDING,
        "mode": mode,
        "job_count": job_count,
        "parsed_count": 0,
        "matched_count": 0,
        "created_at": now,
        "updated_at": now,
        "error": None,
    }


@router.post("/match-runs", status_code=202)
async def create_match_run(body: MatchRunRequest) -> dict:
    deduped: dict[str, None] = {}
    for key in body.job_keys:
        if key not in deduped:
            deduped[key] = None

    jobs: list[dict] = []
    for key in deduped:
        parsed = parse_job_key(key)
        if parsed is None:
            continue
        provider, source_key, job_id = parsed
        row = await fetchone(
            "SELECT * FROM catalog_jobs WHERE provider = ? AND source_key = ? AND job_id = ?",
            (provider, source_key, job_id),
        )
        if row is not None:
            jobs.append(row)

    run_id = generate_run_id()
    manifest = _base_manifest(run_id, body.mode, len(jobs))
    await write_manifest(run_id, manifest)

    asyncio.create_task(execute_match_run(run_id, jobs, body.mode))

    return {"run_id": run_id, "manifest": manifest}


@router.post("/match-runs-with-jd", status_code=202)
async def create_match_run_with_jd(body: MatchRunWithJdRequest) -> dict:
    row = await fetchone(
        "SELECT * FROM catalog_jobs WHERE provider = ? AND source_key = ? AND job_id = ?",
        (body.provider, body.source_key, body.job_id),
    )
    job = (
        row
        if row is not None
        else {
            "provider": body.provider,
            "source_key": body.source_key,
            "job_id": body.job_id,
        }
    )

    run_id = generate_run_id()
    manifest = _base_manifest(run_id, body.mode, 1)
    manifest["parsed_count"] = 1
    await write_manifest(run_id, manifest)

    line = json.dumps(
        {
            **sanitize_job(job),
            "company": company_name(job),
            "jd_text": body.jd_text.strip(),
            "job_url": job.get("job_url"),
            "url": job.get("job_url"),
            "parse_error": None,
        }
    )

    asyncio.create_task(execute_match_run_from_input(run_id, [line], body.mode))

    return {"run_id": run_id, "manifest": manifest}


@router.get("/match-runs/{run_id}")
async def get_match_run(run_id: str) -> dict:
    manifest = await read_manifest(run_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {**manifest, "is_active": run_id in active_run_ids}


@router.get("/match-runs/{run_id}/results")
async def get_match_run_results(run_id: str) -> list:
    return await read_results_jsonl(run_id)
