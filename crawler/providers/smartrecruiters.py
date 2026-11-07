"""SmartRecruiters provider. Ported from crawler/src/providers/smartrecruiters.ts.

Only provider that supports url_template/jobid_template overrides (from
SourceFile.url_template/jobid_template, threaded through CrawlContext) --
paginated JSON API, offset/limit query params added only when absent.
"""

import re
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from models import CrawlContext, NormalizedJob, SourceEntry
from normalizers import first_string, join_strings

provider = "smartrecruiters"

_DEFAULT_URL_TEMPLATE = "https://api.smartrecruiters.com/v1/companies/{identifier}/postings/"
_DEFAULT_JOBID_TEMPLATE = "https://jobs.smartrecruiters.com/{identifier}/{job_id}"
_PAGE_SIZE = 100
_TEMPLATE_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")


async def crawl(source: SourceEntry, context: CrawlContext) -> list[NormalizedJob]:
    identifier = source.identifier
    url_template = context.url_template if context.url_template is not None else _DEFAULT_URL_TEMPLATE
    jobid_template = context.jobid_template if context.jobid_template is not None else _DEFAULT_JOBID_TEMPLATE
    fetched_at = context.fetched_at
    jobs = await fetch_smartrecruiters_jobs(identifier, url_template, context)
    return [normalize_smartrecruiters_job(identifier, job, fetched_at, jobid_template) for job in jobs]


async def fetch_smartrecruiters_jobs(identifier: str, url_template: str, context: CrawlContext) -> list[dict]:
    jobs: list[dict] = []
    offset = 0

    while True:
        url = _with_paging(_render_template(url_template, {"identifier": identifier}), offset, _PAGE_SIZE)
        response = await context.http.get_json(url)
        page = _extract_jobs(response)
        jobs.extend(page)

        if context.max_jobs_per_source is not None and len(jobs) >= context.max_jobs_per_source:
            return jobs[: context.max_jobs_per_source]

        if not _should_fetch_next_page(response, len(page), offset, _PAGE_SIZE):
            return jobs

        offset += _PAGE_SIZE


def normalize_smartrecruiters_job(
    source_key: str, job: dict, fetched_at: str, jobid_template: str = _DEFAULT_JOBID_TEMPLATE
) -> NormalizedJob:
    job_id = (
        first_string(
            job.get("id"),
            job.get("uuid"),
            job.get("jobId"),
            job.get("refNumber"),
            job.get("ref"),
            job.get("name"),
            job.get("title"),
        )
        or "unknown"
    )
    posted_at = first_string(job.get("releasedDate"), job.get("createdOn"))
    location = job.get("location")
    type_of_employment = job.get("typeOfEmployment") or {}
    department_obj = job.get("department") or {}
    function_obj = job.get("function") or {}

    return NormalizedJob(
        provider="smartrecruiters",
        source_key=source_key,
        job_id=job_id,
        title=first_string(job.get("name"), job.get("title")),
        location=_format_location(location),
        employment_type=first_string(type_of_employment.get("label"), type_of_employment.get("name")),
        compensation=None,
        department=first_string(
            department_obj.get("label"),
            department_obj.get("name"),
            function_obj.get("label"),
            function_obj.get("name"),
        ),
        office="Remote" if isinstance(location, dict) and location.get("remote") is True else None,
        language=first_string(job.get("language")),
        updated_at=first_string(job.get("updatedDate"), posted_at),
        posted_at=posted_at,
        job_url=first_string(job.get("postingUrl"), job.get("applyUrl"))
        or _render_template(jobid_template, {"identifier": source_key, "job_id": job_id, "id": job_id}),
        fetched_at=fetched_at,
    )


def _extract_jobs(response: object) -> list[dict]:
    if isinstance(response, list):
        return response
    return response.get("content") or response.get("jobs") or response.get("postings") or []


def _should_fetch_next_page(response: object, page_length: int, offset: int, page_size: int) -> bool:
    if isinstance(response, list):
        return False

    total_found = response.get("totalFound")
    if isinstance(total_found, (int, float)) and not isinstance(total_found, bool):
        return offset + page_length < total_found

    return page_length == page_size


def _render_template(template: str, values: dict[str, str]) -> str:
    def repl(match: re.Match) -> str:
        key = match.group(1)
        if key not in values:
            return match.group(0)
        return quote(values[key])

    return _TEMPLATE_RE.sub(repl, template)


def _with_paging(url: str, offset: int, limit: int) -> str:
    parts = urlsplit(url)
    query_pairs = parse_qsl(parts.query, keep_blank_values=True)
    existing_keys = {key for key, _ in query_pairs}
    if "offset" not in existing_keys:
        query_pairs.append(("offset", str(offset)))
    if "limit" not in existing_keys:
        query_pairs.append(("limit", str(limit)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query_pairs), parts.fragment))


def _format_location(location: object) -> str | None:
    if location is None:
        return None
    if not isinstance(location, dict):
        return None
    return join_strings([location.get("city"), location.get("region"), location.get("country")])
