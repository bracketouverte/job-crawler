import asyncio
import random
import string
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import settings
from services.ensemble_scorer import score_job_ensemble
from services.profile import get_profile
from services.quick_scorer import score_job_quick

router = APIRouter(prefix="/analyze")
runs_router = APIRouter(prefix="/runs")

_RUN_ID_SUFFIX_ALPHABET = string.ascii_lowercase + string.digits

# Keyed by caller-supplied run_id (viewer's own run id) so a concurrent
# request to /runs/{run_id}/cancel or /runs/{run_id}/status can find the
# in-flight analyze task for that run. Entries are removed once the task
# that owns them finishes (success, error, or cancellation).
active_tasks: dict[str, asyncio.Task] = {}
run_status: dict[str, dict] = {}


def _generate_run_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    suffix = "".join(random.choices(_RUN_ID_SUFFIX_ALPHABET, k=6))
    return f"run_{timestamp}_{suffix}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _init_status(run_id: str, job_count: int) -> None:
    now = _now_iso()
    run_status[run_id] = {
        "status": "running",
        "phase": "score",
        "job_count": job_count,
        "processed_count": 0,
        "ok_count": 0,
        "error_count": 0,
        "started_at": now,
        "updated_at": now,
        "error": None,
    }


def _mark_progress(run_id: str, *, ok: bool) -> None:
    row = run_status.get(run_id)
    if row is None:
        return
    row["processed_count"] += 1
    row["ok_count" if ok else "error_count"] += 1
    row["updated_at"] = _now_iso()


def _finish_status(run_id: str, *, status: str, error: str | None = None) -> None:
    row = run_status.get(run_id)
    if row is None:
        return
    row["status"] = status
    row["phase"] = "done"
    row["error"] = error
    row["updated_at"] = _now_iso()


class QuickAnalyzeRequest(BaseModel):
    jobs: list[dict]
    pipeline: str = "maverick"
    run_id: str | None = None


class EnsembleAnalyzeRequest(BaseModel):
    jobs: list[dict]
    pipeline: str = "ensemble"
    run_id: str | None = None


class AnalyzeResponse(BaseModel):
    results: list[dict]
    run_id: str


def _job_row_base(job: dict) -> dict:
    return {
        "provider": job.get("provider"),
        "source_key": job.get("source_key"),
        "job_id": job.get("job_id"),
        "title": job.get("title"),
        "company": job.get("company"),
        "location": job.get("location"),
        "job_url": job.get("job_url") or job.get("url"),
    }


async def _run_quick(jobs: list[dict], run_id: str | None) -> list[dict]:
    profile_data = get_profile()
    results: list[dict] = []

    if run_id:
        _init_status(run_id, len(jobs))

    # Sequential, matching the current job_fit_analyzer.py batch behavior.
    for job in jobs:
        row = _job_row_base(job)
        try:
            analysis = await score_job_quick(job, profile_data, model=settings.nvidia_model)
            row["status"] = "ok"
            row["analysis"] = analysis
            if run_id:
                _mark_progress(run_id, ok=True)
        except Exception as exc:
            row["status"] = "error"
            row["error"] = str(exc)
            if run_id:
                _mark_progress(run_id, ok=False)
        results.append(row)

    return results


@router.post("/quick", response_model=AnalyzeResponse)
async def analyze_quick(body: QuickAnalyzeRequest) -> AnalyzeResponse:
    task = asyncio.create_task(_run_quick(body.jobs, body.run_id))
    if body.run_id:
        active_tasks[body.run_id] = task
    try:
        results = await task
        if body.run_id:
            _finish_status(body.run_id, status="completed")
    except asyncio.CancelledError:
        results = [{"status": "error", "error": "cancelled"}]
        if body.run_id:
            _finish_status(body.run_id, status="cancelled")
    finally:
        if body.run_id:
            active_tasks.pop(body.run_id, None)

    return AnalyzeResponse(results=results, run_id=body.run_id or _generate_run_id())


async def _score_ensemble_row(job: dict, profile_data: dict, run_id: str | None) -> dict:
    row = _job_row_base(job)
    try:
        analysis = await score_job_ensemble(job, profile_data)
        row["status"] = "ok"
        row["analysis"] = analysis
        if run_id:
            _mark_progress(run_id, ok=True)
    except Exception as exc:
        row["status"] = "error"
        row["error"] = str(exc)
        if run_id:
            _mark_progress(run_id, ok=False)
    return row


async def _run_ensemble(jobs: list[dict], run_id: str | None) -> list[dict]:
    profile_data = get_profile()

    if run_id:
        _init_status(run_id, len(jobs))

    if settings.ensemble_job_concurrency <= 1:
        results = [await _score_ensemble_row(job, profile_data, run_id) for job in jobs]
    else:
        semaphore = asyncio.Semaphore(settings.ensemble_job_concurrency)

        async def _bounded(job: dict) -> dict:
            async with semaphore:
                return await _score_ensemble_row(job, profile_data, run_id)

        # gather() preserves output order to match input order regardless of
        # which task actually finishes first.
        results = await asyncio.gather(*(_bounded(job) for job in jobs))

    return results


@router.post("/ensemble", response_model=AnalyzeResponse)
async def analyze_ensemble(body: EnsembleAnalyzeRequest) -> AnalyzeResponse:
    task = asyncio.create_task(_run_ensemble(body.jobs, body.run_id))
    if body.run_id:
        active_tasks[body.run_id] = task
    try:
        results = await task
        if body.run_id:
            _finish_status(body.run_id, status="completed")
    except asyncio.CancelledError:
        results = [{"status": "error", "error": "cancelled"}]
        if body.run_id:
            _finish_status(body.run_id, status="cancelled")
    finally:
        if body.run_id:
            active_tasks.pop(body.run_id, None)

    return AnalyzeResponse(results=results, run_id=body.run_id or _generate_run_id())


@runs_router.post("/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict:
    task = active_tasks.get(run_id)
    if task is None:
        raise HTTPException(status_code=404, detail="run not found")
    task.cancel()
    return {"ok": True}


@runs_router.get("/{run_id}/status")
async def get_run_status(run_id: str) -> dict:
    row = run_status.get(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    return row
