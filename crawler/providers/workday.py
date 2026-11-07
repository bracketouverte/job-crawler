"""Workday provider. Ported from crawler/src/providers/workday.ts.

Highest-risk port in the crawler migration: POST-based offset pagination,
a job_url reconstruction regex, relative-date parsing ("Posted Today",
"Posted 30+ Days Ago", etc.), and a compensation-extraction regex guarded
against false positives on requisition IDs (e.g. "R-12345").
"""

import re
from datetime import UTC, datetime, timedelta

from dateutil import parser as date_parser

from models import CrawlContext, NormalizedJob, SourceEntry
from normalizers import compact_object_strings, first_string, join_strings

provider = "workday"

_PAGE_LIMIT = 20
_MAX_PAGES_PER_SOURCE = 1000

_EXTERNAL_PATH_RE = re.compile(r"^/job/[^/]*/(.+)$")
_LEADING_JOB_RE = re.compile(r"^/job/")
_REQ_ID_RE = re.compile(r"^(req|r|jr|job)[-_]?\d+[a-z0-9-]*$", re.IGNORECASE)
_COMP_KEYWORD_RE = re.compile(
    r"(salary|compensation|base pay|pay range|ote|equity|bonus|hour|annual|year|yr|"
    r"[$€£]|\b\d{2,3}\s?k\b|\b\d{2,3}[,\s]\d{3}\b)",
    re.IGNORECASE,
)
_TODAY_RE = re.compile(r"\btoday\b", re.IGNORECASE)
_YESTERDAY_RE = re.compile(r"\byesterday\b", re.IGNORECASE)
_RELATIVE_RE = re.compile(r"posted\s+(\d+)\+?\s+(day|week|month|year)s?\s+ago", re.IGNORECASE)


async def crawl(source: SourceEntry, context: CrawlContext) -> list[NormalizedJob]:
    jobs: list[dict] = []

    for offset in range(0, _PAGE_LIMIT * _MAX_PAGES_PER_SOURCE, _PAGE_LIMIT):
        page = await _fetch_page(source, offset, context)
        postings = page.get("jobPostings") or []
        jobs.extend(postings)

        total = page.get("total")
        total = total if isinstance(total, (int, float)) and not isinstance(total, bool) else None

        if context.max_jobs_per_source is not None and len(jobs) >= context.max_jobs_per_source:
            break
        if len(postings) < _PAGE_LIMIT or (total is not None and offset + len(postings) >= total):
            break

    key = f"{source.tenant}/{source.shard}/{source.site}"
    jobs_to_return = jobs if context.max_jobs_per_source is None else jobs[: context.max_jobs_per_source]
    return [normalize_workday_job(source, key, job, context.fetched_at) for job in jobs_to_return]


async def _fetch_page(source: SourceEntry, offset: int, context: CrawlContext) -> dict:
    url = f"https://{source.tenant}.{source.shard}.myworkdayjobs.com/wday/cxs/{source.tenant}/{source.site}/jobs"
    return await context.http.post_json(
        url, {"appliedFacets": {}, "limit": _PAGE_LIMIT, "offset": offset, "searchText": ""}
    )


def normalize_workday_job(source: SourceEntry, source_key: str, job: dict, fetched_at: str) -> NormalizedJob:
    job_id = (
        first_string(job.get("jobId"), job.get("id"), job.get("externalPath"), job.get("title")) or "unknown"
    )
    external_path = first_string(job.get("externalPath"))

    job_url = None
    if external_path is not None:
        match = _EXTERNAL_PATH_RE.match(external_path)
        job_path = match.group(1) if match else _LEADING_JOB_RE.sub("", external_path)
        job_url = (
            f"https://{source.tenant}.{source.shard}.myworkdayjobs.com/en-US/{source.site}/job/{job_path}"
        )

    posted_on = first_string(job.get("postedOn"))
    bullet_fields = job.get("bulletFields")

    return NormalizedJob(
        provider="workday",
        source_key=source_key,
        job_id=job_id,
        title=first_string(job.get("title")),
        location=first_string(job.get("locationsText")),
        employment_type=first_string(job.get("timeType"), _infer_bullet(bullet_fields, "time")),
        compensation=_infer_compensation(bullet_fields),
        department=first_string(job.get("jobFamily")),
        office=None,
        language=None,
        updated_at=posted_on,
        posted_at=parse_workday_posted_at(posted_on, fetched_at),
        job_url=job_url,
        fetched_at=fetched_at,
    )


def parse_workday_posted_at(value: str | None, fetched_at: str) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None

    try:
        fetched_dt = date_parser.parse(fetched_at)
    except (ValueError, OverflowError):
        return None
    if fetched_dt.tzinfo is None:
        fetched_dt = fetched_dt.replace(tzinfo=UTC)
    fetched_dt = fetched_dt.astimezone(UTC)

    exact = _try_parse_exact(text)
    if exact is not None:
        return exact

    if _TODAY_RE.search(text):
        return _to_js_iso(_start_of_utc_day(fetched_dt))
    if _YESTERDAY_RE.search(text):
        return _to_js_iso(_start_of_utc_day(fetched_dt) - timedelta(days=1))

    relative = _RELATIVE_RE.search(text)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2).lower()
        days = (
            amount * 365
            if unit == "year"
            else amount * 30 if unit == "month" else amount * 7 if unit == "week" else amount
        )
        return _to_js_iso(_start_of_utc_day(fetched_dt) - timedelta(days=days))

    return None


def _try_parse_exact(text: str) -> str | None:
    try:
        dt = date_parser.parse(text)
    except (ValueError, OverflowError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return _to_js_iso(dt.astimezone(UTC))


def _to_js_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _start_of_utc_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _infer_bullet(values: object, keyword: str) -> str | None:
    if not isinstance(values, list):
        return compact_object_strings(values)

    exact = None
    for value in values:
        text = compact_object_strings(value)
        if text is not None and keyword in text.lower():
            exact = text
            break
    if exact is not None:
        return exact
    return join_strings([compact_object_strings(v) for v in values])


def _infer_compensation(values: object) -> str | None:
    value = _infer_bullet(values, "pay")
    if value is None:
        return None
    if _REQ_ID_RE.match(value):
        return None
    if not _COMP_KEYWORD_RE.search(value):
        return None
    return value
