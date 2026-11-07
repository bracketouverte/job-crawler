import json

import pytest

from services import parser


def test_slugify_token():
    assert parser.slugify_token("Acme & Co.") == "acmeandco"
    assert parser.slugify_token(None) == ""


def test_detect_provider_greenhouse_variants():
    assert parser.detect_provider("https://job-boards.greenhouse.io/acme/jobs/123") == "greenhouse"
    assert parser.detect_provider("https://acme.com/careers?gh_jid=123") == "greenhouse"
    assert parser.detect_provider("https://acme.com/jobs/456") == "greenhouse"


def test_detect_provider_other_boards():
    assert parser.detect_provider("https://jobs.ashbyhq.com/acme/abc") == "ashby"
    assert parser.detect_provider("https://acme.bamboohr.com/careers/1") == "bamboohr"
    assert parser.detect_provider("https://jobs.lever.co/acme/abc") == "lever"
    assert parser.detect_provider("https://acme.teamtailor.com/careers/senior-tpm") == "teamtailor"
    assert (
        parser.detect_provider("https://acme.myworkdayjobs.com/en-US/External/details/Senior-TPM_R12345")
        == "workday"
    )


def test_detect_provider_unsupported_raises():
    with pytest.raises(ValueError):
        parser.detect_provider("https://example.com/careers/random")


def test_detect_provider_from_page():
    assert parser.detect_provider_from_page('<div id="grnhse_app"></div>') == "greenhouse"
    assert parser.detect_provider_from_page("teamtailor-cdn.com asset") == "teamtailor"
    assert parser.detect_provider_from_page("jobs.ashbyhq.com embed") == "ashby"
    assert parser.detect_provider_from_page("<p>nothing here</p>") is None


def test_html_to_lines_strips_tags_and_collapses_whitespace():
    html_text = "<p>Hello   world</p><ul><li>One</li><li>Two</li></ul>"
    lines = parser.html_to_lines(html_text)
    assert "Hello world" in lines
    assert "- One" in lines
    assert "- Two" in lines


def test_extract_sections_from_html_groups_by_heading():
    html_text = "<p>Responsibilities:</p><p>Own the roadmap</p><p>Requirements:</p><p>5+ years experience</p>"
    sections = parser.extract_sections_from_html(html_text)
    assert any("roadmap" in " ".join(v) for v in sections.values())
    assert any("experience" in " ".join(v) for v in sections.values())


def test_bulletize_dedupes_and_limits():
    lines = ["- Own the roadmap", "- Own the roadmap", "- Drive product strategy across teams effectively"]
    result = parser.bulletize(lines, limit=1)
    assert result == ["Own the roadmap"]


def test_infer_workplace_type():
    assert parser.infer_workplace_type("This is a Hybrid role") == "hybrid"
    assert parser.infer_workplace_type("Fully Remote") == "remote"
    assert parser.infer_workplace_type("Work from our office") == "on-site"
    assert parser.infer_workplace_type("") is None


def test_infer_employment_type():
    assert parser.infer_employment_type("Full-time position") == "full-time"
    assert parser.infer_employment_type("This is a part time role") == "part-time"
    assert parser.infer_employment_type("6-month contract") == "contract"
    assert parser.infer_employment_type("Summer internship") == "internship"
    assert parser.infer_employment_type("") is None


def test_infer_compensation_from_explicit_range():
    result = parser.infer_compensation("$150,000 - $180,000", "")
    assert result == {"min": 150000, "max": 180000}


def test_infer_compensation_k_suffix():
    result = parser.infer_compensation("$120k-$140k", "")
    assert result == {"min": 120000, "max": 140000}


def test_infer_compensation_hourly_multiplier():
    result = parser.infer_compensation("$50/hr", "")
    assert result["min"] == 50 * 2080


def test_infer_compensation_none_found():
    assert parser.infer_compensation("", "No numbers here at all") == {"min": None, "max": None}


def test_extract_concepts_ranks_title_phrases_first():
    concepts = parser.extract_concepts(
        "Senior Product Manager", "We need a product manager with SaaS experience."
    )
    assert any("product manager" in c for c in concepts)


def test_build_result_shape():
    result = parser.build_result(
        url="https://example.com/job/1",
        provider="greenhouse",
        title="Senior TPM",
        posted_datetime="2026-01-01",
        location="Remote US",
        compensation={"min": 150000, "max": 180000},
        workplace_type="remote",
        employment_type="full-time",
        responsibilities=["Own the roadmap"],
        requirements_summary=["5+ years experience"],
        concept_text="technical program manager saas",
    )
    assert result["url"] == "https://example.com/job/1"
    assert result["must_have_requirements"] == ["5+ years experience"]
    assert result["nice_to_have_requirements"] == []
    assert "jd_concepts" in result
    assert "technical_tools_mentioned" in result


def test_extract_greenhouse_identifiers_from_path():
    company, job_id = parser.extract_greenhouse_identifiers("https://boards.greenhouse.io/acme/jobs/123")
    assert (company, job_id) == ("acme", "123")


def test_extract_greenhouse_identifiers_from_query_param():
    company, job_id = parser.extract_greenhouse_identifiers(
        "https://acme.com/careers?gh_jid=456",
        raw_html="boards.greenhouse.io/embed/job_board/js?for=acme",
    )
    assert (company, job_id) == ("acme", "456")


def test_extract_greenhouse_identifiers_unsupported_raises():
    with pytest.raises(ValueError):
        parser.extract_greenhouse_identifiers("https://acme.com/careers/random")


def test_greenhouse_page_data_url():
    url = parser.greenhouse_page_data_url("https://acme.com/careers/senior-tpm")
    assert url == "https://acme.com/page-data/careers/senior-tpm/page-data.json"


def test_extract_greenhouse_compensation():
    metadata = [{"name": "Salary Range", "value": "$150k-$180k"}, {"name": "Team", "value": "Platform"}]
    assert parser.extract_greenhouse_compensation(metadata) == "Salary Range: $150k-$180k"
    assert parser.extract_greenhouse_compensation(None) is None


def test_extract_jobposting_ld_json_finds_jobposting_type():
    html_text = (
        '<script type="application/ld+json">'
        '{"@type": "JobPosting", "title": "Senior TPM", "description": "Great role"}'
        "</script>"
    )
    result = parser.extract_jobposting_ld_json(html_text)
    assert result["title"] == "Senior TPM"


def test_extract_jobposting_ld_json_handles_graph():
    payload = {"@graph": [{"@type": "Organization"}, {"@type": "JobPosting", "title": "PM"}]}
    html_text = f'<script type="application/ld+json">{json.dumps(payload)}</script>'
    result = parser.extract_jobposting_ld_json(html_text)
    assert result["title"] == "PM"


def test_extract_jobposting_ld_json_returns_none_when_absent():
    assert parser.extract_jobposting_ld_json("<html><body>no ld+json here</body></html>") is None


def test_extract_ld_json_location():
    jobposting = {
        "jobLocation": {
            "address": {"addressLocality": "Miami", "addressRegion": "FL", "addressCountry": "US"}
        }
    }
    assert parser.extract_ld_json_location(jobposting) == "Miami, FL, US"


def test_extract_ld_json_location_none():
    assert parser.extract_ld_json_location({}) is None


def test_extract_ld_json_compensation():
    jobposting = {
        "baseSalary": {
            "currency": "USD",
            "value": {"minValue": 100000, "maxValue": 120000, "unitText": "YEAR"},
        }
    }
    result = parser.extract_ld_json_compensation(jobposting)
    assert result == {"min": 100000, "max": 120000}


def test_extract_ld_json_compensation_hourly():
    jobposting = {"baseSalary": {"currency": "USD", "value": {"minValue": 50, "unitText": "HOUR"}}}
    result = parser.extract_ld_json_compensation(jobposting)
    assert result["min"] == 50 * 2080


def test_extract_ld_json_compensation_none_when_absent():
    assert parser.extract_ld_json_compensation({}) is None


def test_to_jsonld_serializes_core_fields():
    record = {
        "title": "Senior TPM",
        "company": "Acme",
        "location": "Remote US",
        "employment_type": "full-time",
        "compensation": {"min": 150000, "max": 180000},
        "responsibilities": ["Own the roadmap"],
        "must_have_requirements": ["5+ years"],
        "technical_tools_mentioned": ["SQL"],
    }
    rendered = json.loads(parser.to_jsonld(record, target_role="TPM"))
    assert rendered["title"] == "Senior TPM"
    assert rendered["hiringOrganization"]["name"] == "Acme"
    assert "150k" in rendered["baseSalary"]
    assert "SQL" in rendered["skills"]


@pytest.mark.asyncio
async def test_parse_url_dispatches_to_greenhouse(monkeypatch):
    async def fake_parse_greenhouse(url):
        return {"provider": "greenhouse", "url": url}

    monkeypatch.setattr(parser, "parse_greenhouse", fake_parse_greenhouse)
    result = await parser.parse_url("https://boards.greenhouse.io/acme/jobs/123")
    assert result["provider"] == "greenhouse"


@pytest.mark.asyncio
async def test_parse_url_falls_back_to_generic_for_unsupported_provider(monkeypatch):
    async def fake_generic(url):
        return {"provider": "generic", "url": url}

    monkeypatch.setattr(parser, "parse_generic_jobposting", fake_generic)
    result = await parser.parse_url("https://example.com/careers/random")
    assert result["provider"] == "generic"


@pytest.mark.asyncio
async def test_parse_greenhouse_calls_boards_api(monkeypatch):
    async def fake_fetch_json(url, **kwargs):
        assert "boards-api.greenhouse.io" in url
        return {
            "title": "Senior TPM",
            "content": "<p>Responsibilities:</p><p>Own the roadmap</p>",
            "location": {"name": "Remote US"},
            "first_published": "2026-01-01",
            "metadata": [],
        }

    monkeypatch.setattr(parser, "fetch_json", fake_fetch_json)
    result = await parser.parse_greenhouse("https://boards.greenhouse.io/acme/jobs/123")
    assert result["title"] == "Senior TPM"
    assert result["provider"] == "greenhouse"


@pytest.mark.asyncio
async def test_parse_lever_finds_matching_job(monkeypatch):
    async def fake_fetch_json(url, **kwargs):
        return [
            {
                "id": "abc",
                "text": "Senior TPM",
                "lists": [{"text": "Responsibilities", "content": "<p>Own the roadmap</p>"}],
                "categories": {"location": "Remote US", "commitment": "Full-time"},
                "createdAt": 1700000000000,
                "descriptionPlain": "Great role",
            }
        ]

    monkeypatch.setattr(parser, "fetch_json", fake_fetch_json)
    result = await parser.parse_lever("https://jobs.lever.co/acme/abc")
    assert result["title"] == "Senior TPM"
    assert result["provider"] == "lever"


@pytest.mark.asyncio
async def test_parse_lever_job_not_found_raises(monkeypatch):
    async def fake_fetch_json(url, **kwargs):
        return []

    monkeypatch.setattr(parser, "fetch_json", fake_fetch_json)
    with pytest.raises(ValueError):
        await parser.parse_lever("https://jobs.lever.co/acme/missing")


@pytest.mark.asyncio
async def test_parse_bamboohr(monkeypatch):
    async def fake_fetch_json(url, **kwargs):
        return {
            "result": {
                "jobOpening": {
                    "jobOpeningName": "Senior TPM",
                    "location": {"city": "Miami", "state": "FL", "addressCountry": "US"},
                    "description": "<p>Requirements:</p><p>5+ years experience</p>",
                    "datePosted": "2026-01-01",
                }
            }
        }

    monkeypatch.setattr(parser, "fetch_json", fake_fetch_json)
    result = await parser.parse_bamboohr("https://acme.bamboohr.com/careers/1")
    assert result["title"] == "Senior TPM"
    assert result["location"] == "Miami, FL, US"


@pytest.mark.asyncio
async def test_parse_generic_jobposting(monkeypatch):
    payload = {
        "@type": "JobPosting",
        "title": "Senior TPM",
        "description": "<p>Requirements:</p><p>5+ years</p>",
    }

    async def fake_fetch_text(url, **kwargs):
        return f'<script type="application/ld+json">{json.dumps(payload)}</script>'

    monkeypatch.setattr(parser, "fetch_text", fake_fetch_text)
    result = await parser.parse_generic_jobposting("https://acme.teamtailor.com/jobs/1")
    assert result["title"] == "Senior TPM"


@pytest.mark.asyncio
async def test_parse_generic_jobposting_raises_when_no_ld_json(monkeypatch):
    async def fake_fetch_text(url, **kwargs):
        return "<html><body>nothing here</body></html>"

    monkeypatch.setattr(parser, "fetch_text", fake_fetch_text)
    with pytest.raises(ValueError):
        await parser.parse_generic_jobposting("https://acme.teamtailor.com/jobs/1")


@pytest.mark.asyncio
async def test_fetch_json_and_fetch_text_require_started_client():
    parser._client = None
    with pytest.raises(RuntimeError):
        await parser.fetch_json("https://example.com")
    with pytest.raises(RuntimeError):
        await parser.fetch_text("https://example.com")


@pytest.mark.asyncio
async def test_start_and_stop_client_lifecycle():
    parser.start_client()
    assert parser._client is not None
    await parser.stop_client()
    assert parser._client is None
