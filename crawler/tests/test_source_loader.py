import json

import pytest

from models import SourceEntry
from source_loader import (
    is_provider,
    load_source_file,
    parse_provider_list,
    source_key,
)


def test_source_key_identifier_based():
    assert source_key(SourceEntry(identifier="acme")) == "acme"


def test_source_key_workday():
    entry = SourceEntry(tenant="acme", shard="wd1", site="External")
    assert source_key(entry) == "acme/wd1/External"


def test_is_provider():
    assert is_provider("greenhouse") is True
    assert is_provider("not-a-provider") is False


def test_parse_provider_list_all():
    result = parse_provider_list("all")
    assert set(result) == {
        "ashby",
        "bamboohr",
        "greenhouse",
        "icims",
        "lever",
        "smartrecruiters",
        "teamtailor",
        "workable",
        "workday",
    }


def test_parse_provider_list_comma_separated():
    assert parse_provider_list("greenhouse, lever") == ["greenhouse", "lever"]


def test_parse_provider_list_empty_raises():
    with pytest.raises(ValueError, match="must not be empty"):
        parse_provider_list("  ,  ")


def test_parse_provider_list_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unsupported provider"):
        parse_provider_list("greenhouse,not-a-provider")


def test_load_source_file_missing_file_soft_fails(tmp_path, capsys):
    result = load_source_file(str(tmp_path), "greenhouse")
    assert result.provider == "greenhouse"
    assert result.companies == []
    captured = capsys.readouterr()
    assert "not found" in captured.out


def test_load_source_file_valid(tmp_path):
    data = {
        "provider": "greenhouse",
        "companies": [{"identifier": "acme"}, {"identifier": "beta"}],
    }
    (tmp_path / "greenhouse.json").write_text(json.dumps(data))

    result = load_source_file(str(tmp_path), "greenhouse")
    assert result.provider == "greenhouse"
    assert [c.identifier for c in result.companies] == ["acme", "beta"]


def test_load_source_file_workday_requires_tenant_shard_site(tmp_path):
    data = {
        "provider": "workday",
        "companies": [{"tenant": "acme", "shard": "wd1", "site": "External"}],
    }
    (tmp_path / "workday.json").write_text(json.dumps(data))

    result = load_source_file(str(tmp_path), "workday")
    assert result.companies[0].tenant == "acme"


def test_load_source_file_workday_missing_field_raises(tmp_path):
    data = {"provider": "workday", "companies": [{"tenant": "acme", "shard": "wd1"}]}
    (tmp_path / "workday.json").write_text(json.dumps(data))

    with pytest.raises(ValueError, match="site must be a non-empty string"):
        load_source_file(str(tmp_path), "workday")


def test_load_source_file_wrong_provider_declared_raises(tmp_path):
    data = {"provider": "lever", "companies": []}
    (tmp_path / "greenhouse.json").write_text(json.dumps(data))

    with pytest.raises(ValueError, match="declares provider"):
        load_source_file(str(tmp_path), "greenhouse")


def test_load_source_file_companies_not_array_raises(tmp_path):
    data = {"provider": "greenhouse", "companies": "not-a-list"}
    (tmp_path / "greenhouse.json").write_text(json.dumps(data))

    with pytest.raises(ValueError, match="must contain a companies array"):
        load_source_file(str(tmp_path), "greenhouse")


def test_load_source_file_empty_identifier_raises(tmp_path):
    data = {"provider": "greenhouse", "companies": [{"identifier": ""}]}
    (tmp_path / "greenhouse.json").write_text(json.dumps(data))

    with pytest.raises(ValueError, match="identifier must be a non-empty string"):
        load_source_file(str(tmp_path), "greenhouse")


def test_load_source_file_with_templates(tmp_path):
    data = {
        "provider": "smartrecruiters",
        "url_template": "https://api.example.com/{identifier}",
        "jobid_template": "{job_id}",
        "companies": [{"identifier": "acme"}],
    }
    (tmp_path / "smartrecruiters.json").write_text(json.dumps(data))

    result = load_source_file(str(tmp_path), "smartrecruiters")
    assert result.url_template == "https://api.example.com/{identifier}"
    assert result.jobid_template == "{job_id}"


def test_load_source_file_non_string_template_raises(tmp_path):
    data = {"provider": "greenhouse", "companies": [], "url_template": 123}
    (tmp_path / "greenhouse.json").write_text(json.dumps(data))

    with pytest.raises(ValueError, match="must be a string when present"):
        load_source_file(str(tmp_path), "greenhouse")
