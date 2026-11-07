import pytest

from models import CrawlContext, SourceEntry
from providers import icims

_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://careers-acme.icims.com/jobs/intro</loc></url>
  <url><loc>https://careers-acme.icims.com/jobs/search?ss=1</loc></url>
  <url><loc>https://careers-acme.icims.com/jobs/123/financial-service-representative/job</loc></url>
  <url><loc>https://careers-acme.icims.com/jobs/456/senior-software-engineer/job</loc></url>
</urlset>
"""


def test_parse_icims_sitemap_extracts_job_urls():
    jobs = icims.parse_icims_sitemap("acme", _SITEMAP, "2026-01-01T00:00:00Z")
    assert len(jobs) == 2
    assert jobs[0].job_id == "123"
    assert jobs[0].title == "Financial Service Representative"
    assert jobs[0].job_url == "https://careers-acme.icims.com/jobs/123/financial-service-representative/job"
    assert jobs[1].job_id == "456"
    assert jobs[1].title == "Senior Software Engineer"


def test_parse_icims_sitemap_skips_intro_and_non_job_urls():
    jobs = icims.parse_icims_sitemap("acme", _SITEMAP, "2026-01-01T00:00:00Z")
    urls = [j.job_url for j in jobs]
    assert "https://careers-acme.icims.com/jobs/intro" not in urls
    assert "https://careers-acme.icims.com/jobs/search?ss=1" not in urls


def test_parse_icims_sitemap_sets_provider_and_fetched_at_and_nulls_out_unavailable_fields():
    jobs = icims.parse_icims_sitemap("acme", _SITEMAP, "2026-01-01T00:00:00Z")
    job = jobs[0]
    assert job.provider == "icims"
    assert job.source_key == "acme"
    assert job.fetched_at == "2026-01-01T00:00:00Z"
    assert job.location is None
    assert job.employment_type is None
    assert job.compensation is None
    assert job.posted_at is None


def test_parse_icims_sitemap_empty_returns_no_jobs():
    assert icims.parse_icims_sitemap("acme", "<urlset></urlset>", "2026-01-01T00:00:00Z") == []


@pytest.mark.asyncio
async def test_crawl_strips_careers_prefix_from_identifier():
    seen_urls = []

    class FakeHttp:
        async def get_text(self, url, **kwargs):
            seen_urls.append(url)
            return _SITEMAP

    context = CrawlContext(http=FakeHttp(), fetched_at="2026-01-01T00:00:00Z")
    jobs = await icims.crawl(SourceEntry(identifier="careers-acme"), context)
    assert seen_urls == ["https://careers-acme.icims.com/sitemap.xml"]
    assert jobs[0].source_key == "acme"


@pytest.mark.asyncio
async def test_crawl_bare_slug_identifier():
    seen_urls = []

    class FakeHttp:
        async def get_text(self, url, **kwargs):
            seen_urls.append(url)
            return _SITEMAP

    context = CrawlContext(http=FakeHttp(), fetched_at="2026-01-01T00:00:00Z")
    await icims.crawl(SourceEntry(identifier="acme"), context)
    assert seen_urls == ["https://careers-acme.icims.com/sitemap.xml"]


@pytest.mark.asyncio
async def test_crawl_empty_slug_after_stripping_returns_no_jobs_and_no_fetch():
    class FakeHttp:
        async def get_text(self, url, **kwargs):
            raise AssertionError("should not fetch when slug is empty")

    context = CrawlContext(http=FakeHttp(), fetched_at="2026-01-01T00:00:00Z")
    jobs = await icims.crawl(SourceEntry(identifier="careers-"), context)
    assert jobs == []
