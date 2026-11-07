import pytest

from config import DEFAULT_PROVIDER_CONCURRENCY, parse_args, parse_provider_concurrency


def test_defaults_match_no_arguments():
    options = parse_args([])
    assert options.sources == "/data/sources"
    assert options.providers == "all"
    assert options.concurrency == 50
    assert options.out == "/app/output/jobs.jsonl"
    assert options.report == "/app/output/report.json"
    assert options.catalog_db == "/app/state/catalog.sqlite"
    assert options.exclude_sources is None
    assert options.progress_every_ms == 10000
    assert options.timeout_ms == 15000
    assert options.retries == 2
    assert options.progress_file == "/app/state/crawler-progress.json"
    assert options.provider_concurrency == DEFAULT_PROVIDER_CONCURRENCY


def test_provider_concurrency_override_parses_into_dict():
    options = parse_args(["--provider-concurrency", "ashby=1,workday=4"])
    assert options.provider_concurrency == {"ashby": 1, "workday": 4}


def test_provider_concurrency_override_replaces_not_merges_defaults():
    options = parse_args(["--provider-concurrency", "ashby=1"])
    assert options.provider_concurrency == {"ashby": 1}
    assert "bamboohr" not in options.provider_concurrency


def test_parse_provider_concurrency_empty_raises():
    with pytest.raises(ValueError, match="must not be empty"):
        parse_provider_concurrency("")


def test_parse_provider_concurrency_invalid_entry_raises():
    with pytest.raises(ValueError, match="Expected provider=limit"):
        parse_provider_concurrency("ashby")


def test_parse_provider_concurrency_unknown_provider_raises():
    with pytest.raises(ValueError, match="Expected provider=limit"):
        parse_provider_concurrency("not-a-provider=5")


def test_parse_provider_concurrency_non_positive_raises():
    with pytest.raises(ValueError, match="positive integer"):
        parse_provider_concurrency("ashby=0")


def test_concurrency_must_be_positive_integer():
    with pytest.raises(SystemExit):
        parse_args(["--concurrency", "0"])


def test_progress_every_ms_accepts_zero():
    options = parse_args(["--progress-every-ms", "0"])
    assert options.progress_every_ms == 0


def test_progress_every_ms_rejects_negative():
    with pytest.raises(SystemExit):
        parse_args(["--progress-every-ms", "-1"])


def test_max_age_hours_optional_default_none():
    options = parse_args([])
    assert options.max_age_hours is None
    options = parse_args(["--max-age-hours", "48"])
    assert options.max_age_hours == 48


def test_catalog_file_flag_not_recognized():
    # --catalog-file is dropped per the resolved migration-plan decision.
    with pytest.raises(SystemExit):
        parse_args(["--catalog-file", "/tmp/x.jsonl"])
