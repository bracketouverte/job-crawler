import pytest

from models import CrawlContext, SourceEntry
from providers import smartrecruiters


def test_normalize_basic_fields():
    job = {
        "id": "123",
        "name": "Senior Backend Engineer",
        "location": {"city": "Miami", "region": "FL", "country": "USA"},
        "typeOfEmployment": {"label": "Full-time"},
        "department": {"label": "Engineering"},
        "releasedDate": "2026-01-01T00:00:00Z",
        "postingUrl": "https://jobs.smartrecruiters.com/acme/123",
    }
    result = smartrecruiters.normalize_smartrecruiters_job("acme", job, "2026-01-02T00:00:00Z")
    assert result.provider == "smartrecruiters"
    assert result.job_id == "123"
    assert result.title == "Senior Backend Engineer"
    assert result.location == "Miami, FL, USA"
    assert result.employment_type == "Full-time"
    assert result.department == "Engineering"
    assert result.posted_at == "2026-01-01T00:00:00Z"
    assert result.job_url == "https://jobs.smartrecruiters.com/acme/123"
    assert result.fetched_at == "2026-01-02T00:00:00Z"


def test_normalize_job_id_falls_back_through_chain():
    job = {"uuid": "u-1", "title": "Only Title"}
    result = smartrecruiters.normalize_smartrecruiters_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.job_id == "u-1"


def test_normalize_missing_id_falls_back_to_unknown():
    result = smartrecruiters.normalize_smartrecruiters_job("acme", {}, "2026-01-01T00:00:00Z")
    assert result.job_id == "unknown"


def test_normalize_office_remote_when_location_remote_true():
    job = {"id": "1", "location": {"remote": True}}
    result = smartrecruiters.normalize_smartrecruiters_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.office == "Remote"


def test_normalize_office_none_when_location_missing():
    result = smartrecruiters.normalize_smartrecruiters_job("acme", {"id": "1"}, "2026-01-01T00:00:00Z")
    assert result.office is None


def test_normalize_job_url_falls_back_to_jobid_template():
    job = {"id": "123"}
    result = smartrecruiters.normalize_smartrecruiters_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.job_url == "https://jobs.smartrecruiters.com/acme/123"


def test_normalize_job_url_uses_custom_jobid_template():
    job = {"id": "123"}
    result = smartrecruiters.normalize_smartrecruiters_job(
        "acme", job, "2026-01-01T00:00:00Z", jobid_template="https://custom.example.com/{identifier}/{job_id}"
    )
    assert result.job_url == "https://custom.example.com/acme/123"


def test_normalize_department_falls_back_to_function():
    job = {"id": "1", "function": {"name": "R&D"}}
    result = smartrecruiters.normalize_smartrecruiters_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.department == "R&D"


@pytest.mark.asyncio
async def test_crawl_uses_default_templates_and_normalizes():
    class FakeHttp:
        async def get_json(self, url, **kwargs):
            assert "api.smartrecruiters.com/v1/companies/acme/postings" in url
            return {"content": [{"id": "1", "title": "Engineer"}], "totalFound": 1}

    context = CrawlContext(http=FakeHttp(), fetched_at="2026-01-01T00:00:00Z")
    jobs = await smartrecruiters.crawl(SourceEntry(identifier="acme"), context)
    assert len(jobs) == 1
    assert jobs[0].title == "Engineer"


@pytest.mark.asyncio
async def test_crawl_uses_context_url_template_override():
    seen_urls = []

    class FakeHttp:
        async def get_json(self, url, **kwargs):
            seen_urls.append(url)
            return {"content": [], "totalFound": 0}

    context = CrawlContext(
        http=FakeHttp(),
        fetched_at="2026-01-01T00:00:00Z",
        url_template="https://custom.example.com/{identifier}/jobs",
    )
    await smartrecruiters.crawl(SourceEntry(identifier="acme"), context)
    assert seen_urls[0].startswith("https://custom.example.com/acme/jobs")


@pytest.mark.asyncio
async def test_fetch_paginates_until_total_found_reached():
    call_count = {"n": 0}

    class FakeHttp:
        async def get_json(self, url, **kwargs):
            call_count["n"] += 1
            offset = 0 if "offset=0" in url else 100
            content = [{"id": str(offset + i)} for i in range(100)] if offset == 0 else [{"id": "200"}]
            return {"content": content, "totalFound": 101}

    context = CrawlContext(http=FakeHttp(), fetched_at="2026-01-01T00:00:00Z")
    jobs = await smartrecruiters.fetch_smartrecruiters_jobs(
        "acme", "https://api.smartrecruiters.com/v1/companies/{identifier}/postings/", context
    )
    assert len(jobs) == 101
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_fetch_stops_when_page_shorter_than_page_size_and_no_total_found():
    class FakeHttp:
        async def get_json(self, url, **kwargs):
            return {"content": [{"id": "1"}]}

    context = CrawlContext(http=FakeHttp(), fetched_at="2026-01-01T00:00:00Z")
    jobs = await smartrecruiters.fetch_smartrecruiters_jobs(
        "acme", "https://api.smartrecruiters.com/v1/companies/{identifier}/postings/", context
    )
    assert len(jobs) == 1


@pytest.mark.asyncio
async def test_fetch_handles_bare_array_response_no_pagination():
    class FakeHttp:
        async def get_json(self, url, **kwargs):
            return [{"id": "1"}, {"id": "2"}]

    context = CrawlContext(http=FakeHttp(), fetched_at="2026-01-01T00:00:00Z")
    jobs = await smartrecruiters.fetch_smartrecruiters_jobs(
        "acme", "https://api.smartrecruiters.com/v1/companies/{identifier}/postings/", context
    )
    assert len(jobs) == 2


@pytest.mark.asyncio
async def test_fetch_respects_max_jobs_per_source():
    class FakeHttp:
        async def get_json(self, url, **kwargs):
            return {"content": [{"id": str(i)} for i in range(100)], "totalFound": 500}

    context = CrawlContext(http=FakeHttp(), fetched_at="2026-01-01T00:00:00Z", max_jobs_per_source=5)
    jobs = await smartrecruiters.fetch_smartrecruiters_jobs(
        "acme", "https://api.smartrecruiters.com/v1/companies/{identifier}/postings/", context
    )
    assert len(jobs) == 5


def test_with_paging_does_not_override_existing_offset_limit():
    url = smartrecruiters._with_paging("https://example.com/postings?offset=9&limit=50", 0, 100)
    assert "offset=9" in url
    assert "limit=50" in url
