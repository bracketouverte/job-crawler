import json
import logging
import math
import re
from datetime import UTC, datetime, timedelta

import aiofiles
import httpx

import config
from db import fetchone
from services import queue_store
from services.analysis import analysis_score_5
from services.company import (
    company_logo_url,
    company_website,
    decision_emoji,
    job_compensation,
    job_mode,
    normalize_label,
)

logger = logging.getLogger(__name__)

_ID_SANITIZE_RE = re.compile(r"[^a-z0-9_]", re.IGNORECASE)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


async def read_score_notifications() -> dict:
    try:
        async with aiofiles.open(config.SCORE_NOTIFICATIONS_PATH, encoding="utf-8") as f:
            raw = await f.read()
        parsed = json.loads(raw)
        sent = parsed.get("sent")
        return {"sent": sent if isinstance(sent, dict) else {}}
    except (OSError, ValueError):
        return {"sent": {}}


async def write_score_notifications(state: dict) -> None:
    async with aiofiles.open(config.SCORE_NOTIFICATIONS_PATH, "w", encoding="utf-8") as f:
        await f.write(json.dumps(state, indent=2) + "\n")


async def read_hidden_jobs() -> set[str]:
    try:
        async with aiofiles.open(config.HIDDEN_JOBS_PATH, encoding="utf-8") as f:
            raw = await f.read()
        parsed = json.loads(raw)
        hidden = parsed.get("hidden")
        return {key for key in hidden if isinstance(key, str)} if isinstance(hidden, list) else set()
    except (OSError, ValueError):
        return set()


async def write_hidden_jobs(hidden: set[str]) -> None:
    async with aiofiles.open(config.HIDDEN_JOBS_PATH, "w", encoding="utf-8") as f:
        await f.write(json.dumps({"hidden": sorted(hidden), "updated_at": _now_iso()}, indent=2) + "\n")


async def notify_discord_for_score(row: dict, run_id: str) -> bool:
    if not config.DISCORD_WEBHOOK_URL or not math.isfinite(config.SCORE_NOTIFY_MIN_SCORE):
        return False

    score = analysis_score_5(row.get("analysis"))
    if score is None or score < config.SCORE_NOTIFY_MIN_SCORE:
        return False

    provider = row.get("provider")
    source_key = row.get("source_key")
    job_id = row.get("job_id")
    if not (isinstance(provider, str) and isinstance(source_key, str) and isinstance(job_id, str)):
        return False

    key = f"{provider}|{source_key}|{job_id}"
    notifications = await read_score_notifications()
    existing = notifications["sent"].get(key)
    if existing and existing.get("score_5", float("-inf")) >= score:
        return False

    title = str(row.get("title") or "Job")
    company = str(row.get("company") or source_key)

    job_url = str(row.get("job_url") or row.get("url") or "")
    if not job_url:
        db_row = await fetchone(
            "SELECT job_url FROM catalog_jobs WHERE provider = ? AND source_key = ? AND job_id = ?",
            (provider, source_key, job_id),
        )
        job_url = str((db_row or {}).get("job_url") or "")

    thumbnail_url = company_logo_url(company)
    company_url = company_website(company)
    analysis = row.get("analysis")
    role_summary = analysis.get("role_summary") if isinstance(analysis, dict) else None
    role_summary = role_summary if isinstance(role_summary, dict) else {}
    tldr = str(role_summary["tldr"]) if role_summary.get("tldr") else None
    domain = str(role_summary["domain"]) if role_summary.get("domain") else None
    valid_job_url = job_url if job_url.startswith("http://") or job_url.startswith("https://") else None

    embed: dict = {}
    if company_url:
        embed["author"] = {"name": company, "url": company_url}
    embed["title"] = title
    if valid_job_url:
        embed["url"] = valid_job_url
    embed["color"] = 3066993
    if tldr:
        embed["description"] = tldr
    if thumbnail_url:
        embed["thumbnail"] = {"url": thumbnail_url}

    fields = [
        {"name": "Score", "value": f"{score:.1f}/5", "inline": True},
        {"name": "Company", "value": company or "n/a", "inline": True},
        {"name": "Location", "value": normalize_label(row.get("location")) or "n/a", "inline": True},
        {"name": "Mode", "value": job_mode(row.get("location"), row.get("employment_type")), "inline": True},
        {"name": "Compensation", "value": job_compensation(row.get("compensation")), "inline": True},
    ]
    if domain:
        fields.append({"name": "Domain", "value": domain, "inline": True})
    fields.append({"name": "Decision", "value": decision_emoji(score), "inline": False})
    embed["fields"] = fields

    payload = {"username": "Job Scanner", "embeds": [embed], "allowed_mentions": {"parse": []}}

    async with httpx.AsyncClient() as client:
        response = await client.post(config.DISCORD_WEBHOOK_URL, json=payload)

    if response.status_code >= 400:
        err_msg = f"Discord webhook failed with status {response.status_code}"
        raw_id = f"discord_{run_id}_{provider}_{source_key}_{job_id}"
        discord_queue_id = _ID_SANITIZE_RE.sub("_", raw_id)
        now = _now_iso()
        await queue_store.upsert_queue_item(
            {
                "id": discord_queue_id,
                "job_key": key,
                "title": title,
                "company": company,
                "mode": "discord-only",
                "status": "retrying",
                "subtasks": [{"id": "discord", "label": "Discord push", "status": "error", "error": err_msg}],
                "attempt": 1,
                "max_attempts": 3,
                "next_retry_at": (datetime.now(UTC) + timedelta(seconds=60))
                .isoformat()
                .replace("+00:00", "Z"),
                "created_at": now,
                "updated_at": now,
                "error": json.dumps({**row, "_run_id": run_id}),
            }
        )
        raise RuntimeError(err_msg)

    notifications["sent"][key] = {"score_5": score, "notified_at": _now_iso(), "run_id": run_id}
    await write_score_notifications(notifications)
    return True
