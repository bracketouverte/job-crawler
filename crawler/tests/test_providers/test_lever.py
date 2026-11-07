import pytest

from models import CrawlContext, SourceEntry
from providers import lever


def test_normalize_lever_job_basic_fields():
    job = {
        "id": "abc",
        "text": "Senior PM",
        "hostedUrl": "https://jobs.lever.co/acme/abc",
        "categories": {"location": "Remote", "commitment": "Full-time", "team": "Product"},
        "workplaceType": "remote",
        "createdAt": 1735689600000,  # 2025-01-01T00:00:00Z in ms
    }
    result = lever.normalize_lever_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.provider == "lever"
    assert result.job_id == "abc"
    assert result.title == "Senior PM"
    assert result.location == "Remote"
    assert result.employment_type == "Full-time"
    assert result.department == "Product"
    assert result.office == "remote"
    assert result.job_url == "https://jobs.lever.co/acme/abc"
    assert result.updated_at == result.posted_at == "2025-01-01T00:00:00Z"


def test_normalize_lever_job_id_falls_back_to_hosted_url_then_text():
    job = {"hostedUrl": "https://jobs.lever.co/acme/xyz", "text": "Engineer"}
    result = lever.normalize_lever_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.job_id == "https://jobs.lever.co/acme/xyz"


def test_normalize_lever_job_missing_created_at_leaves_dates_none():
    job = {"id": "1", "text": "Engineer"}
    result = lever.normalize_lever_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.updated_at is None
    assert result.posted_at is None


def test_normalize_lever_job_non_numeric_created_at_leaves_dates_none():
    job = {"id": "1", "text": "Engineer", "createdAt": "not-a-number"}
    result = lever.normalize_lever_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.updated_at is None
    assert result.posted_at is None


def test_normalize_lever_job_url_falls_back_to_apply_url():
    job = {"id": "1", "text": "Engineer", "applyUrl": "https://jobs.lever.co/acme/1/apply"}
    result = lever.normalize_lever_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.job_url == "https://jobs.lever.co/acme/1/apply"


def test_normalize_lever_job_department_falls_back_to_department_field():
    job = {"id": "1", "text": "Engineer", "categories": {"department": "R&D"}}
    result = lever.normalize_lever_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.department == "R&D"


@pytest.mark.asyncio
async def test_crawl_calls_postings_api_and_normalizes():
    class FakeHttp:
        async def get_json(self, url, **kwargs):
            assert "api.lever.co/v0/postings/acme" in url
            return [{"id": "1", "text": "Engineer"}]

    context = CrawlContext(http=FakeHttp(), fetched_at="2026-01-01T00:00:00Z")
    jobs = await lever.crawl(SourceEntry(identifier="acme"), context)
    assert len(jobs) == 1
    assert jobs[0].title == "Engineer"
