import pytest

from models import CrawlContext, SourceEntry
from providers import workable


def test_normalize_basic_fields():
    job = {
        "shortcode": "abc123",
        "title": "Senior Backend Engineer",
        "city": "Miami",
        "state": "FL",
        "country": "USA",
        "employment_type": "full",
        "department": "Engineering",
        "published_on": "2026-01-01",
        "url": "https://apply.workable.com/acme/j/abc123",
    }
    result = workable.normalize_workable_job("acme", job, "2026-01-02T00:00:00Z")
    assert result.provider == "workable"
    assert result.job_id == "abc123"
    assert result.title == "Senior Backend Engineer"
    assert result.location == "Miami, FL, USA"
    assert result.employment_type == "full"
    assert result.department == "Engineering"
    assert result.updated_at == result.posted_at == "2026-01-01"
    assert result.job_url == "https://apply.workable.com/acme/j/abc123"


def test_normalize_job_id_falls_back_through_chain():
    job = {"code": "c-1", "title": "Only Title"}
    result = workable.normalize_workable_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.job_id == "c-1"


def test_normalize_location_prefers_locations_array_over_flat_fields():
    job = {
        "shortcode": "1",
        "locations": [{"city": "Miami", "region": "FL", "country": "USA", "hidden": False}],
        "city": "Ignored",
    }
    result = workable.normalize_workable_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.location == "Miami, FL, USA"


def test_normalize_location_filters_hidden_entries():
    job = {
        "shortcode": "1",
        "locations": [
            {"city": "Miami", "hidden": True},
            {"city": "Austin", "hidden": False},
        ],
    }
    result = workable.normalize_workable_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.location == "Austin"


def test_normalize_location_joins_multiple_visible_with_pipe():
    job = {
        "shortcode": "1",
        "locations": [{"city": "Miami"}, {"city": "Austin"}],
    }
    result = workable.normalize_workable_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.location == "Miami | Austin"


def test_normalize_location_falls_back_to_flat_fields_when_no_locations():
    job = {"shortcode": "1", "city": "Miami", "state": "FL"}
    result = workable.normalize_workable_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.location == "Miami, FL"


def test_normalize_office_remote_when_telecommuting_true():
    job = {"shortcode": "1", "telecommuting": True}
    result = workable.normalize_workable_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.office == "Remote"


def test_normalize_office_none_when_telecommuting_false_or_missing():
    result = workable.normalize_workable_job("acme", {"shortcode": "1"}, "2026-01-01T00:00:00Z")
    assert result.office is None


def test_normalize_job_url_falls_back_to_shortlink_then_application_url():
    job = {"shortcode": "1", "application_url": "https://apply.example.com/1"}
    result = workable.normalize_workable_job("acme", job, "2026-01-01T00:00:00Z")
    assert result.job_url == "https://apply.example.com/1"


@pytest.mark.asyncio
async def test_crawl_calls_widget_api_and_normalizes():
    class FakeHttp:
        async def get_json(self, url, **kwargs):
            assert "apply.workable.com/api/v1/widget/accounts/acme" in url
            return {"jobs": [{"shortcode": "1", "title": "Engineer"}]}

    context = CrawlContext(http=FakeHttp(), fetched_at="2026-01-01T00:00:00Z")
    jobs = await workable.crawl(SourceEntry(identifier="acme"), context)
    assert len(jobs) == 1
    assert jobs[0].title == "Engineer"


@pytest.mark.asyncio
async def test_crawl_handles_missing_jobs_key():
    class FakeHttp:
        async def get_json(self, url, **kwargs):
            return {}

    context = CrawlContext(http=FakeHttp(), fetched_at="2026-01-01T00:00:00Z")
    jobs = await workable.crawl(SourceEntry(identifier="acme"), context)
    assert jobs == []
