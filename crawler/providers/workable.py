"""Workable provider. Ported from crawler/src/providers/workable.ts."""

from urllib.parse import quote

from models import CrawlContext, NormalizedJob, SourceEntry
from normalizers import first_string, join_strings

provider = "workable"


async def crawl(source: SourceEntry, context: CrawlContext) -> list[NormalizedJob]:
    identifier = source.identifier
    url = f"https://apply.workable.com/api/v1/widget/accounts/{quote(identifier)}"
    response = await context.http.get_json(url)
    jobs = response.get("jobs") or []
    return [normalize_workable_job(identifier, job, context.fetched_at) for job in jobs]


def normalize_workable_job(source_key: str, job: dict, fetched_at: str) -> NormalizedJob:
    job_id = (
        first_string(job.get("shortcode"), job.get("code"), job.get("url"), job.get("title")) or "unknown"
    )
    return NormalizedJob(
        provider="workable",
        source_key=source_key,
        job_id=job_id,
        title=first_string(job.get("title")),
        location=first_string(
            _format_locations(job.get("locations")),
            _format_location(job.get("city"), job.get("state"), job.get("country")),
        ),
        employment_type=first_string(job.get("employment_type")),
        compensation=None,
        department=first_string(job.get("department"), job.get("function")),
        office=_office_type(job.get("telecommuting")),
        language=None,
        updated_at=first_string(job.get("published_on"), job.get("created_at")),
        posted_at=first_string(job.get("published_on"), job.get("created_at")),
        job_url=first_string(job.get("url"), job.get("shortlink"), job.get("application_url")),
        fetched_at=fetched_at,
    )


def _format_locations(locations: object) -> str | None:
    if not isinstance(locations, list):
        return None

    visible = []
    for location in locations:
        if not isinstance(location, dict) or location.get("hidden") is True:
            continue
        formatted = _format_location(location.get("city"), location.get("region"), location.get("country"))
        if formatted is not None:
            visible.append(formatted)

    return join_strings(visible, " | ")


def _format_location(city: object, region: object, country: object) -> str | None:
    parts = [p for p in (first_string(city), first_string(region), first_string(country)) if p is not None]
    return ", ".join(parts) if parts else None


def _office_type(telecommuting: object) -> str | None:
    return "Remote" if telecommuting is True else None
