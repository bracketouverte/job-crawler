"""BambooHR provider. Ported from crawler/src/providers/bamboohr.ts.

Classified as an HTML-scraping provider by the runner (jittered HttpClient)
even though this endpoint returns JSON -- that's about the site's
rate-limiting behavior, not the response format, and is a runner concern
(Epic 6), not this module's.
"""

from models import CrawlContext, NormalizedJob, SourceEntry
from normalizers import first_string

provider = "bamboohr"


async def crawl(source: SourceEntry, context: CrawlContext) -> list[NormalizedJob]:
    identifier = source.identifier
    url = f"https://{identifier}.bamboohr.com/careers/list"
    response = await context.http.get_json(url, headers={"Accept": "application/json"})
    jobs = response if isinstance(response, list) else (response.get("result") or [])
    return [normalize_bamboo_job(identifier, job, context.fetched_at) for job in jobs]


def normalize_bamboo_job(source_key: str, job: dict, fetched_at: str) -> NormalizedJob:
    job_id = first_string(job.get("id"), job.get("jobOpeningName"), job.get("title")) or "unknown"
    return NormalizedJob(
        provider="bamboohr",
        source_key=source_key,
        job_id=job_id,
        title=first_string(job.get("jobOpeningName"), job.get("title")),
        location=first_string(job.get("location")),
        employment_type=first_string(job.get("employmentStatus")),
        compensation=None,
        department=first_string(job.get("departmentLabel")),
        office=None,
        language=None,
        updated_at=first_string(job.get("datePosted")),
        posted_at=first_string(job.get("datePosted")),
        # job_url is always constructed -- never taken from the API response.
        job_url=f"https://{source_key}.bamboohr.com/careers/{job_id}/detail",
        fetched_at=fetched_at,
    )
