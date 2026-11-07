import pytest

from models import CrawlContext, SourceEntry
from providers import ashby


def test_normalize_ashby_job_basic_fields():
    job = {
        "id": "job-1",
        "title": "Staff Engineer",
        "location": "Remote - US",
        "employmentType": "FullTime",
        "department": "Engineering",
        "workplaceType": "Remote",
        "publishedAt": "2026-01-01T00:00:00Z",
        "jobUrl": "https://jobs.ashbyhq.com/acme/job-1",
    }
    result = ashby.normalize_ashby_job("acme", job, "2026-01-02T00:00:00Z")
    assert result.provider == "ashby"
    assert result.job_id == "job-1"
    assert result.title == "Staff Engineer"
    assert result.location == "Remote - US"
    assert result.employment_type == "FullTime"
    assert result.department == "Engineering"
    assert result.office == "Remote"
    assert result.updated_at == result.posted_at == "2026-01-01T00:00:00Z"
    assert result.job_url == "https://jobs.ashbyhq.com/acme/job-1"


def test_normalize_ashby_job_url_constructed_when_missing():
    job = {"id": "job-1", "title": "Engineer"}
    result = ashby.normalize_ashby_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.job_url == "https://jobs.ashbyhq.com/acme/job-1"


def test_normalize_ashby_job_department_falls_back_to_team():
    job = {"id": "1", "title": "Engineer", "team": "Platform"}
    result = ashby.normalize_ashby_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.department == "Platform"


def test_normalize_ashby_job_id_falls_back_to_title():
    job = {"title": "Only Title"}
    result = ashby.normalize_ashby_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.job_id == "Only Title"


@pytest.mark.asyncio
async def test_crawl_calls_job_board_api_and_normalizes():
    class FakeHttp:
        async def get_json(self, url, **kwargs):
            assert "api.ashbyhq.com/posting-api/job-board/acme" in url
            return {"jobs": [{"id": "1", "title": "Engineer"}]}

    context = CrawlContext(http=FakeHttp(), fetched_at="2026-01-01T00:00:00Z")
    jobs = await ashby.crawl(SourceEntry(identifier="acme"), context)
    assert len(jobs) == 1
    assert jobs[0].title == "Engineer"
