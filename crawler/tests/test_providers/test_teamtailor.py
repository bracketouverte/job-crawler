import pytest

from models import CrawlContext, SourceEntry
from providers import teamtailor

_RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:teamtailor="https://teamtailor.com">
  <channel>
    <title>Acme Careers</title>
    <item>
      <title>Senior Backend Engineer</title>
      <link>https://acme.teamtailor.com/jobs/123-senior-backend-engineer</link>
      <guid>https://acme.teamtailor.com/jobs/123-senior-backend-engineer</guid>
      <pubDate>Tue, 20 Jan 2026 08:00:00 GMT</pubDate>
      <category>Engineering</category>
      <teamtailor:department>R&amp;D</teamtailor:department>
      <teamtailor:location>Miami, FL</teamtailor:location>
    </item>
    <item>
      <title>Product Manager</title>
      <link>https://acme.teamtailor.com/jobs/456-product-manager</link>
      <guid>https://acme.teamtailor.com/jobs/456-product-manager</guid>
      <pubDate>Wed, 21 Jan 2026 08:00:00 GMT</pubDate>
      <category>Product</category>
      <category>Remote</category>
    </item>
  </channel>
</rss>
"""


def test_parse_items_extracts_both_items():
    items = teamtailor._parse_items(_RSS_SAMPLE)
    assert len(items) == 2
    assert items[0]["title"] == "Senior Backend Engineer"
    assert items[0]["department"] == "R&D"
    assert items[0]["location"] == "Miami, FL"


def test_parse_items_collects_repeated_category_as_list():
    items = teamtailor._parse_items(_RSS_SAMPLE)
    assert items[1]["category"] == ["Product", "Remote"]


def test_normalize_basic_fields():
    items = teamtailor._parse_items(_RSS_SAMPLE)
    result = teamtailor.normalize_teamtailor_job("acme", items[0], "2026-01-22T00:00:00Z")
    assert result.provider == "teamtailor"
    assert result.job_id == "https://acme.teamtailor.com/jobs/123-senior-backend-engineer"
    assert result.title == "Senior Backend Engineer"
    assert result.location == "Miami, FL"
    assert result.department == "R&D"
    assert result.job_url == "https://acme.teamtailor.com/jobs/123-senior-backend-engineer"
    assert result.updated_at == result.posted_at == "2026-01-20T08:00:00.000Z"


def test_normalize_department_falls_back_to_joined_category():
    items = teamtailor._parse_items(_RSS_SAMPLE)
    result = teamtailor.normalize_teamtailor_job("acme", items[1], "2026-01-22T00:00:00Z")
    assert result.department == "Product, Remote"


def test_normalize_job_id_falls_back_to_link_then_title():
    item = {"title": "Only Title"}
    result = teamtailor.normalize_teamtailor_job("acme", item, "2026-01-01T00:00:00Z")
    assert result.job_id == "Only Title"


def test_parse_date_returns_raw_value_when_unparseable():
    assert teamtailor._parse_date("not a date") == "not a date"


def test_parse_date_returns_none_for_none():
    assert teamtailor._parse_date(None) is None


@pytest.mark.asyncio
async def test_crawl_fetches_rss_and_normalizes():
    class FakeHttp:
        async def get_text(self, url, **kwargs):
            assert url == "https://acme.teamtailor.com/jobs.rss"
            return _RSS_SAMPLE

    context = CrawlContext(http=FakeHttp(), fetched_at="2026-01-22T00:00:00Z")
    jobs = await teamtailor.crawl(SourceEntry(identifier="acme"), context)
    assert len(jobs) == 2
    assert jobs[0].title == "Senior Backend Engineer"
