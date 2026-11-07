import pytest

from models import CrawlContext, SourceEntry
from providers import bamboohr


def test_normalize_bamboo_job_basic_fields():
    job = {
        "id": 42,
        "jobOpeningName": "Backend Engineer",
        "location": "Miami, FL",
        "departmentLabel": "Engineering",
        "employmentStatus": "Full-Time",
        "datePosted": "2026-01-01",
    }
    result = bamboohr.normalize_bamboo_job("acme", job, "2026-01-02T00:00:00Z")
    assert result.provider == "bamboohr"
    assert result.job_id == "42"
    assert result.title == "Backend Engineer"
    assert result.location == "Miami, FL"
    assert result.department == "Engineering"
    assert result.employment_type == "Full-Time"
    assert result.updated_at == result.posted_at == "2026-01-01"
    # job_url is always constructed, never taken from the API response.
    assert result.job_url == "https://acme.bamboohr.com/careers/42/detail"


def test_normalize_bamboo_job_title_falls_back_when_no_job_opening_name():
    job = {"id": 1, "title": "Fallback Title"}
    result = bamboohr.normalize_bamboo_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.title == "Fallback Title"


def test_normalize_bamboo_job_url_ignores_any_url_field_in_response():
    job = {"id": 1, "jobOpeningName": "Engineer", "url": "https://example.com/should-be-ignored"}
    result = bamboohr.normalize_bamboo_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.job_url == "https://acme.bamboohr.com/careers/1/detail"


@pytest.mark.asyncio
async def test_crawl_handles_bare_array_response():
    class FakeHttp:
        async def get_json(self, url, headers=None, **kwargs):
            assert "acme.bamboohr.com/careers/list" in url
            assert headers == {"Accept": "application/json"}
            return [{"id": 1, "jobOpeningName": "Engineer"}]

    context = CrawlContext(http=FakeHttp(), fetched_at="2026-01-01T00:00:00Z")
    jobs = await bamboohr.crawl(SourceEntry(identifier="acme"), context)
    assert len(jobs) == 1


@pytest.mark.asyncio
async def test_crawl_handles_wrapped_result_response():
    class FakeHttp:
        async def get_json(self, url, headers=None, **kwargs):
            return {"result": [{"id": 1, "jobOpeningName": "Engineer"}]}

    context = CrawlContext(http=FakeHttp(), fetched_at="2026-01-01T00:00:00Z")
    jobs = await bamboohr.crawl(SourceEntry(identifier="acme"), context)
    assert len(jobs) == 1
