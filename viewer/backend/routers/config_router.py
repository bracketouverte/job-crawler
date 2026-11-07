import json
from datetime import datetime, timedelta
from pathlib import Path

import aiofiles
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import config
from services.company import logo_dev_brand_cache
from services.notifications import read_hidden_jobs, write_hidden_jobs

router = APIRouter(prefix="/api")

_SCHEDULE_HOURS = [8, 10, 12, 14, 16, 18, 20]


def _short_model_name(full_id: str) -> str:
    return full_id.split("/")[-1] if full_id else full_id


@router.get("/config")
async def get_config() -> dict:
    scorer_env = config.NVIDIA_ENSEMBLE_SCORERS or (
        "meta/llama-4-maverick-17b-128e-instruct,moonshotai/kimi-k2.6,"
        "nvidia/llama-3.3-nemotron-super-49b-v1.5"
    )
    synth_env = config.NVIDIA_ENSEMBLE_SYNTHESIZER or "nvidia/llama-3.3-nemotron-super-49b-v1.5"
    scorers = [_short_model_name(m.strip()) for m in scorer_env.split(",") if m.strip()]
    return {
        "ensembleScorers": scorers,
        "ensembleSynthesizer": _short_model_name(synth_env.strip()),
        "logoDevPublishableKey": config.LOGO_DEV_PUBLISHABLE_KEY,
        "scoreNotifyMinScore": config.SCORE_NOTIFY_MIN_SCORE,
        "userLocation": config.USER_LOCATION,
        "savedSearchAnalyzerEnabled": config.SAVED_SEARCH_ANALYZER_ENABLED,
    }


def _next_scheduled_run() -> str:
    now = datetime.now()
    for hour in _SCHEDULE_HOURS:
        candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate > now:
            return candidate.isoformat()
    tomorrow = (now + timedelta(days=1)).replace(hour=_SCHEDULE_HOURS[0], minute=0, second=0, microsecond=0)
    return tomorrow.isoformat()


@router.get("/crawl-status")
async def get_crawl_status() -> dict:
    try:
        async with aiofiles.open(config.CRAWLER_PROGRESS_PATH, encoding="utf-8") as f:
            raw = await f.read()
        progress = json.loads(raw.strip())
    except (OSError, ValueError):
        return {"active": True, "progress": None, "next_run": _next_scheduled_run()}

    active = Path(config.CRAWLER_ACTIVE_LOCK_PATH).exists()
    return {"active": active, "progress": progress, "next_run": _next_scheduled_run()}


@router.get("/hidden-jobs")
async def get_hidden_jobs() -> dict:
    hidden = await read_hidden_jobs()
    return {"hidden": sorted(hidden)}


class HiddenJobsBody(BaseModel):
    hidden: list[str]


@router.put("/hidden-jobs")
async def put_hidden_jobs(body: HiddenJobsBody) -> dict:
    hidden = {key.strip() for key in body.hidden if isinstance(key, str) and key.strip()}
    await write_hidden_jobs(hidden)
    return {"hidden": sorted(hidden)}


@router.get("/logo-dev/brand")
async def get_logo_dev_brand(company: str = "") -> dict:
    if not config.LOGO_DEV_SECRET_KEY:
        return {"domain": None}

    company = company.strip()
    if not company:
        raise HTTPException(status_code=400, detail="company is required")

    cache_key = company.lower()
    if cache_key in logo_dev_brand_cache:
        return {"domain": logo_dev_brand_cache[cache_key]}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.logo.dev/search",
                params={"q": company, "strategy": "match"},
                headers={"Authorization": f"Bearer {config.LOGO_DEV_SECRET_KEY}"},
            )
        if response.status_code >= 400:
            raise RuntimeError(f"Logo.dev search failed with status {response.status_code}")
        data = response.json()
        domain = (str(data[0].get("domain") or "").strip() or None) if data else None
    except Exception:
        raise HTTPException(status_code=502, detail="Logo.dev brand search failed")

    logo_dev_brand_cache[cache_key] = domain
    return {"domain": domain}
