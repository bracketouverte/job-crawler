import pytest

from models import CrawlContext, SourceEntry
from providers import workday


def _source(**overrides) -> SourceEntry:
    defaults = dict(tenant="acme", shard="wd1", site="External")
    defaults.update(overrides)
    return SourceEntry(**defaults)


def test_normalize_basic_fields():
    job = {
        "jobId": "R-123",
        "title": "Senior Backend Engineer",
        "locationsText": "Miami, FL",
        "timeType": "Full time",
        "jobFamily": "Engineering",
        "postedOn": "2026-01-01T00:00:00Z",
        "externalPath": "/job/DUNDEE-GBR/Product-Manager_R1151951",
    }
    result = workday.normalize_workday_job(_source(), "acme/wd1/External", job, "2026-01-02T00:00:00Z")
    assert result.provider == "workday"
    assert result.job_id == "R-123"
    assert result.title == "Senior Backend Engineer"
    assert result.location == "Miami, FL"
    assert result.employment_type == "Full time"
    assert result.department == "Engineering"
    assert result.job_url == "https://acme.wd1.myworkdayjobs.com/en-US/External/job/Product-Manager_R1151951"


def test_normalize_job_url_falls_back_when_path_does_not_match_regex():
    job = {"jobId": "1", "externalPath": "/job/weird-shape"}
    result = workday.normalize_workday_job(_source(), "acme/wd1/External", job, "2026-01-01T00:00:00Z")
    assert result.job_url == "https://acme.wd1.myworkdayjobs.com/en-US/External/job/weird-shape"


def test_normalize_job_url_none_when_no_external_path():
    result = workday.normalize_workday_job(
        _source(), "acme/wd1/External", {"jobId": "1"}, "2026-01-01T00:00:00Z"
    )
    assert result.job_url is None


def test_normalize_job_id_falls_back_through_chain():
    job = {"externalPath": "/job/x/y", "title": "Only Title"}
    result = workday.normalize_workday_job(_source(), "acme/wd1/External", job, "2026-01-01T00:00:00Z")
    assert result.job_id == "/job/x/y"


class TestParseWorkdayPostedAt:
    def test_returns_none_for_none(self):
        assert workday.parse_workday_posted_at(None, "2026-01-15T12:00:00Z") is None

    def test_returns_none_for_blank(self):
        assert workday.parse_workday_posted_at("   ", "2026-01-15T12:00:00Z") is None

    def test_parses_exact_iso_date(self):
        result = workday.parse_workday_posted_at("2026-01-10T00:00:00Z", "2026-01-15T12:00:00Z")
        assert result == "2026-01-10T00:00:00.000Z"

    def test_today_resolves_to_start_of_fetched_utc_day(self):
        result = workday.parse_workday_posted_at("Posted Today", "2026-01-15T18:30:00Z")
        assert result == "2026-01-15T00:00:00.000Z"

    def test_yesterday_resolves_to_previous_utc_day(self):
        result = workday.parse_workday_posted_at("Posted Yesterday", "2026-01-15T18:30:00Z")
        assert result == "2026-01-14T00:00:00.000Z"

    def test_relative_days_ago(self):
        result = workday.parse_workday_posted_at("Posted 3 Days Ago", "2026-01-15T00:00:00Z")
        assert result == "2026-01-12T00:00:00.000Z"

    def test_relative_days_ago_with_plus(self):
        result = workday.parse_workday_posted_at("Posted 30+ Days Ago", "2026-01-31T00:00:00Z")
        assert result == "2026-01-01T00:00:00.000Z"

    def test_relative_weeks_ago(self):
        result = workday.parse_workday_posted_at("Posted 2 Weeks Ago", "2026-01-15T00:00:00Z")
        assert result == "2026-01-01T00:00:00.000Z"

    def test_relative_months_ago(self):
        result = workday.parse_workday_posted_at("Posted 1 Month Ago", "2026-01-31T00:00:00Z")
        assert result == "2026-01-01T00:00:00.000Z"

    def test_unparseable_returns_none(self):
        assert workday.parse_workday_posted_at("gibberish nonsense text", "2026-01-15T00:00:00Z") is None


class TestInferCompensation:
    def test_detects_salary_keyword(self):
        bullet_fields = [{"text": "Salary: $120k - $150k"}]
        assert (
            workday.normalize_workday_job(
                _source(), "k", {"jobId": "1", "bulletFields": bullet_fields}, "2026-01-01T00:00:00Z"
            ).compensation
            == "Salary: $120k - $150k"
        )

    def test_rejects_requisition_id_shaped_text(self):
        assert workday._infer_compensation([{"text": "R-0012345"}]) is None

    def test_none_when_no_pay_keyword_bullet(self):
        assert workday._infer_compensation([{"text": "Full time"}]) is None

    def test_none_when_pay_bullet_lacks_compensation_signal(self):
        assert workday._infer_compensation([{"text": "Pay grade internal use only"}]) is None


class TestInferBullet:
    def test_finds_bullet_matching_keyword(self):
        assert workday._infer_bullet([{"text": "Full time"}, {"text": "Remote"}], "time") == "Full time"

    def test_falls_back_to_joined_bullets_when_no_match(self):
        result = workday._infer_bullet([{"text": "Remote"}, {"text": "Engineering"}], "time")
        assert result == "Remote, Engineering"

    def test_non_list_value_uses_compact_object_strings(self):
        assert workday._infer_bullet({"text": "Full time"}, "time") == "Full time"


@pytest.mark.asyncio
async def test_crawl_paginates_until_short_page():
    calls = []

    class FakeHttp:
        async def post_json(self, url, body, **kwargs):
            calls.append(body["offset"])
            if body["offset"] == 0:
                return {"jobPostings": [{"jobId": str(i)} for i in range(20)], "total": 25}
            return {"jobPostings": [{"jobId": str(i)} for i in range(5)], "total": 25}

    context = CrawlContext(http=FakeHttp(), fetched_at="2026-01-01T00:00:00Z")
    jobs = await workday.crawl(_source(), context)
    assert len(jobs) == 25
    assert calls == [0, 20]


@pytest.mark.asyncio
async def test_crawl_respects_max_jobs_per_source():
    class FakeHttp:
        async def post_json(self, url, body, **kwargs):
            return {"jobPostings": [{"jobId": str(i)} for i in range(20)], "total": 100}

    context = CrawlContext(http=FakeHttp(), fetched_at="2026-01-01T00:00:00Z", max_jobs_per_source=5)
    jobs = await workday.crawl(_source(), context)
    assert len(jobs) == 5
