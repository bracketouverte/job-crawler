"""Ashby provider. Ported from crawler/src/providers/ashby.ts."""

from urllib.parse import quote

from models import CrawlContext, NormalizedJob, SourceEntry
from normalizers import first_string

provider = "ashby"


async def crawl(source: SourceEntry, context: CrawlContext) -> list[NormalizedJob]:
    identifier = source.identifier
    url = f"https://api.ashbyhq.com/posting-api/job-board/{quote(identifier)}"
    response = await context.http.get_json(url)
    jobs = response.get("jobs") or []
    return [normalize_ashby_job(identifier, job, context.fetched_at) for job in jobs]


def normalize_ashby_job(source_key: str, job: dict, fetched_at: str) -> NormalizedJob:
    job_id = first_string(job.get("id"), job.get("title")) or "unknown"
    return NormalizedJob(
        provider="ashby",
        source_key=source_key,
        job_id=job_id,
        title=first_string(job.get("title")),
        location=first_string(job.get("location")),
        employment_type=first_string(job.get("employmentType")),
        compensation=None,
        department=first_string(job.get("department"), job.get("team")),
        office=first_string(job.get("workplaceType")),
        language=None,
        updated_at=first_string(job.get("publishedAt")),
        posted_at=first_string(job.get("publishedAt")),
        job_url=first_string(job.get("jobUrl")) or f"https://jobs.ashbyhq.com/{source_key}/{job_id}",
        fetched_at=fetched_at,
    )
