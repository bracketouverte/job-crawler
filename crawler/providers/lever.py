"""Lever provider. Ported from crawler/src/providers/lever.ts."""

from datetime import UTC, datetime
from urllib.parse import quote

from models import CrawlContext, NormalizedJob, SourceEntry
from normalizers import first_string

provider = "lever"


async def crawl(source: SourceEntry, context: CrawlContext) -> list[NormalizedJob]:
    identifier = source.identifier
    url = f"https://api.lever.co/v0/postings/{quote(identifier)}?mode=json"
    jobs = await context.http.get_json(url)
    return [normalize_lever_job(identifier, job, context.fetched_at) for job in jobs]


def _created_at_iso(job: dict) -> str | None:
    created_at = job.get("createdAt")
    if not isinstance(created_at, (int, float)) or isinstance(created_at, bool):
        return None
    return datetime.fromtimestamp(created_at / 1000, tz=UTC).isoformat().replace("+00:00", "Z")


def normalize_lever_job(source_key: str, job: dict, fetched_at: str) -> NormalizedJob:
    job_id = first_string(job.get("id"), job.get("hostedUrl"), job.get("text")) or "unknown"
    categories = job.get("categories") or {}
    # Lever only exposes createdAt -- no updatedAt field exists in their API.
    created_at_iso = _created_at_iso(job)
    return NormalizedJob(
        provider="lever",
        source_key=source_key,
        job_id=job_id,
        title=first_string(job.get("text")),
        location=first_string(categories.get("location")),
        employment_type=first_string(categories.get("commitment")),
        compensation=None,
        department=first_string(categories.get("team"), categories.get("department")),
        office=first_string(job.get("workplaceType")),
        language=None,
        updated_at=created_at_iso,
        posted_at=created_at_iso,
        job_url=first_string(job.get("hostedUrl"), job.get("applyUrl")),
        fetched_at=fetched_at,
    )
