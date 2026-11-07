"""Greenhouse provider. Ported from crawler/src/providers/greenhouse.ts."""

from urllib.parse import quote

from models import CrawlContext, NormalizedJob, SourceEntry
from normalizers import first_string, join_strings

provider = "greenhouse"


async def crawl(source: SourceEntry, context: CrawlContext) -> list[NormalizedJob]:
    identifier = source.identifier
    url = f"https://boards-api.greenhouse.io/v1/boards/{quote(identifier)}/jobs?content=true"
    response = await context.http.get_json(url)
    jobs = response.get("jobs") or []
    return [normalize_greenhouse_job(identifier, job, context.fetched_at) for job in jobs]


def normalize_greenhouse_job(source_key: str, job: dict, fetched_at: str) -> NormalizedJob:
    job_id = first_string(job.get("id"), job.get("internal_job_id"), job.get("title")) or "unknown"
    location = job.get("location") or {}
    departments = job.get("departments") or []
    offices = job.get("offices") or []
    return NormalizedJob(
        provider="greenhouse",
        source_key=source_key,
        job_id=job_id,
        title=first_string(job.get("title")),
        location=first_string(location.get("name")),
        employment_type=None,
        compensation=_extract_compensation(job),
        department=join_strings([item.get("name") for item in departments]),
        office=join_strings([item.get("name") for item in offices]),
        language=first_string(job.get("language")),
        # Greenhouse's API doesn't expose a distinct posted date -- both
        # fields reuse updated_at, matching the TS version.
        updated_at=first_string(job.get("updated_at")),
        posted_at=first_string(job.get("updated_at")),
        job_url=first_string(job.get("absolute_url")),
        fetched_at=fetched_at,
    )


def _extract_compensation(job: dict) -> str | None:
    metadata = job.get("metadata")
    if not metadata or not isinstance(metadata, (list, dict)):
        return None

    entries = metadata if isinstance(metadata, list) else list(metadata.values())
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        label = first_string(entry.get("name"), entry.get("label"))
        if label and ("compensation" in label.lower() or "salary" in label.lower()):
            return first_string(entry.get("value"), entry.get("name"))
    return None
