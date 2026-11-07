import json

import pytest

from exclusions import exclusion_key, is_excluded, load_excluded_sources


def test_load_excluded_sources_none_path_returns_empty_set():
    assert load_excluded_sources(None) == set()


def test_load_excluded_sources_parses_provider_and_source_key(tmp_path):
    path = tmp_path / "exclude.jsonl"
    path.write_text(json.dumps({"provider": "greenhouse", "source_key": "acme"}) + "\n")
    result = load_excluded_sources(str(path))
    assert result == {"greenhouse:acme"}


def test_load_excluded_sources_accepts_ats_and_identifier_aliases(tmp_path):
    path = tmp_path / "exclude.jsonl"
    path.write_text(json.dumps({"ats": "lever", "identifier": "beta"}) + "\n")
    result = load_excluded_sources(str(path))
    assert result == {"lever:beta"}


def test_load_excluded_sources_skips_blank_lines(tmp_path):
    path = tmp_path / "exclude.jsonl"
    path.write_text('\n{"provider": "greenhouse", "source_key": "acme"}\n\n')
    result = load_excluded_sources(str(path))
    assert result == {"greenhouse:acme"}


def test_load_excluded_sources_missing_file_raises(tmp_path):
    with pytest.raises(OSError):
        load_excluded_sources(str(tmp_path / "does-not-exist.jsonl"))


def test_load_excluded_sources_invalid_json_raises_with_line_number(tmp_path):
    path = tmp_path / "exclude.jsonl"
    path.write_text("not json\n")
    with pytest.raises(ValueError, match=r"exclude\.jsonl:1 is not valid JSON"):
        load_excluded_sources(str(path))


def test_load_excluded_sources_unsupported_provider_raises(tmp_path):
    path = tmp_path / "exclude.jsonl"
    path.write_text(json.dumps({"provider": "not-a-provider", "source_key": "acme"}) + "\n")
    with pytest.raises(ValueError, match="unsupported provider"):
        load_excluded_sources(str(path))


def test_load_excluded_sources_empty_source_key_raises(tmp_path):
    path = tmp_path / "exclude.jsonl"
    path.write_text(json.dumps({"provider": "greenhouse", "source_key": ""}) + "\n")
    with pytest.raises(ValueError, match="non-empty source_key"):
        load_excluded_sources(str(path))


def test_exclusion_key_format():
    assert exclusion_key("greenhouse", "acme") == "greenhouse:acme"


def test_is_excluded():
    excluded = {"greenhouse:acme"}
    assert is_excluded(excluded, "greenhouse", "acme") is True
    assert is_excluded(excluded, "greenhouse", "beta") is False
    assert is_excluded(excluded, "lever", "acme") is False
