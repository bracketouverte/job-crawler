"""iCIMS provider. Ported from crawler/src/providers/icims.ts.

Mechanism: XML sitemap scraping, not a JSON API. Only title (reconstructed
from the URL slug), job_url, and job_id are available -- location,
employment_type, compensation, and posted_at are structurally absent.
Had zero unit test coverage in the TS version; this port adds it.
"""

import re
from urllib.parse import unquote

from models import CrawlContext, NormalizedJob, SourceEntry

provider = "icims"

_CAREERS_PREFIX_RE = re.compile(r"^careers-")
_LEADING_DASH_RE = re.compile(r"^-")
_LOC_RE = re.compile(r"<loc>\s*(https?://[^\s<]+)\s*</loc>")
_WORD_START_RE = re.compile(r"\b\w")


async def crawl(source: SourceEntry, context: CrawlContext) -> list[NormalizedJob]:
    identifier = source.identifier or ""
    # The source list was harvested from Common Crawl full domain names, so
    # some identifiers already carry the "careers-" prefix (e.g.
    # "careers-acme") while others are bare slugs (e.g. "acme"). Normalise
    # to the bare slug before constructing the URL to avoid
    # "careers-careers-acme.icims.com".
    slug = _LEADING_DASH_RE.sub("", _CAREERS_PREFIX_RE.sub("", identifier))
    if slug == "":
        return []
    sitemap_url = f"https://careers-{slug}.icims.com/sitemap.xml"
    xml_text = await context.http.get_text(sitemap_url)
    return parse_icims_sitemap(slug, xml_text, context.fetched_at)


def parse_icims_sitemap(identifier: str, xml_text: str, fetched_at: str) -> list[NormalizedJob]:
    locs = _LOC_RE.findall(xml_text)

    jobs: list[NormalizedJob] = []
    for job_url in locs:
        # Job URLs look like: https://careers-{slug}.icims.com/jobs/{id}/{title-slug}/job
        # Skip non-job URLs (intro pages, search pages, etc.)
        if "/jobs/" not in job_url or job_url.endswith("/jobs/intro") or not job_url.endswith("/job"):
            continue

        after_jobs = job_url.split("/jobs/", 1)[1]
        # parts: ["<id>", "<title-slug>", "job"]
        parts = after_jobs.split("/")
        job_id = parts[0] if len(parts) > 0 else None
        title_slug = parts[1] if len(parts) > 1 else None

        if job_id is None or title_slug is None:
            continue

        # Reconstruct title from URL slug: "financial-service-representative"
        # -> "Financial Service Representative"
        title = _WORD_START_RE.sub(lambda m: m.group(0).upper(), unquote(title_slug).replace("-", " "))

        jobs.append(
            NormalizedJob(
                provider="icims",
                source_key=identifier,
                job_id=job_id,
                title=title,
                location=None,
                employment_type=None,
                compensation=None,
                department=None,
                office=None,
                language=None,
                updated_at=None,
                posted_at=None,
                job_url=job_url,
                fetched_at=fetched_at,
            )
        )

    return jobs
