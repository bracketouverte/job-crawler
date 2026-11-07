import pytest

from models import CrawlContext, SourceEntry
from providers import greenhouse


def test_normalize_greenhouse_job_basic_fields():
    job = {
        "id": 123,
        "title": "Senior Backend Engineer",
        "location": {"name": "Miami, FL"},
        "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
        "updated_at": "2026-01-01T00:00:00Z",
        "departments": [{"name": "Engineering"}],
        "offices": [{"name": "Remote"}, {"name": "Miami"}],
    }
    result = greenhouse.normalize_greenhouse_job("acme", job, "2026-01-02T00:00:00Z")
    assert result.provider == "greenhouse"
    assert result.job_id == "123"
    assert result.title == "Senior Backend Engineer"
    assert result.location == "Miami, FL"
    assert result.job_url == "https://boards.greenhouse.io/acme/jobs/123"
    # updated_at and posted_at both reuse the same field -- Greenhouse has
    # no separate posted date.
    assert result.updated_at == "2026-01-01T00:00:00Z"
    assert result.posted_at == "2026-01-01T00:00:00Z"
    assert result.department == "Engineering"
    assert result.office == "Remote, Miami"
    assert result.fetched_at == "2026-01-02T00:00:00Z"


def test_normalize_greenhouse_job_id_falls_back_to_internal_job_id_then_title():
    job = {"title": "Only Title"}
    result = greenhouse.normalize_greenhouse_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.job_id == "Only Title"


def test_normalize_greenhouse_job_missing_id_and_title_is_unknown():
    result = greenhouse.normalize_greenhouse_job("acme", {}, "2026-01-01T00:00:00Z")
    assert result.job_id == "unknown"


def test_extract_compensation_finds_entry_by_label_substring():
    job = {
        "metadata": [
            {"name": "Team Size", "value": "5"},
            {"name": "Compensation Range", "value": "$150k-$180k"},
        ]
    }
    result = greenhouse.normalize_greenhouse_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.compensation == "$150k-$180k"


def test_extract_compensation_matches_salary_keyword():
    job = {"metadata": [{"label": "Salary", "value": "$100k"}]}
    result = greenhouse.normalize_greenhouse_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.compensation == "$100k"


def test_extract_compensation_none_when_no_matching_metadata():
    job = {"metadata": [{"name": "Team Size", "value": "5"}]}
    result = greenhouse.normalize_greenhouse_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.compensation is None


def test_extract_compensation_handles_dict_metadata_shape():
    job = {"metadata": {"a": {"name": "Compensation", "value": "$120k"}}}
    result = greenhouse.normalize_greenhouse_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.compensation == "$120k"


def test_extract_compensation_handles_missing_metadata():
    result = greenhouse.normalize_greenhouse_job("acme", {}, "2026-01-01T00:00:00Z")
    assert result.compensation is None


@pytest.mark.asyncio
async def test_crawl_calls_boards_api_and_normalizes():
    class FakeHttp:
        async def get_json(self, url, **kwargs):
            assert "boards-api.greenhouse.io/v1/boards/acme/jobs" in url
            return {"jobs": [{"id": 1, "title": "Engineer"}]}

    context = CrawlContext(http=FakeHttp(), fetched_at="2026-01-01T00:00:00Z")
    jobs = await greenhouse.crawl(SourceEntry(identifier="acme"), context)
    assert len(jobs) == 1
    assert jobs[0].title == "Engineer"


@pytest.mark.asyncio
async def test_crawl_handles_missing_jobs_key():
    class FakeHttp:
        async def get_json(self, url, **kwargs):
            return {}

    context = CrawlContext(http=FakeHttp(), fetched_at="2026-01-01T00:00:00Z")
    jobs = await greenhouse.crawl(SourceEntry(identifier="acme"), context)
    assert jobs == []
