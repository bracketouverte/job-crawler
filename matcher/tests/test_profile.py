import pytest

from services import profile as profile_service


def test_load_profile_reads_all_four_files(profile_dir, profile_data):
    loaded = profile_service.load_profile(str(profile_dir))
    assert loaded == profile_data


def test_load_profile_caches_result(profile_dir):
    first = profile_service.load_profile(str(profile_dir))
    (profile_dir / "profile.yml").write_text("changed", encoding="utf-8")
    second = profile_service.load_profile(str(profile_dir))
    assert first is second


def test_get_profile_before_load_raises():
    with pytest.raises(RuntimeError):
        profile_service.get_profile()


def test_get_profile_after_load_returns_cache(profile_dir, profile_data):
    profile_service.load_profile(str(profile_dir))
    assert profile_service.get_profile() == profile_data


def test_invalidate_profile_cache(profile_dir):
    profile_service.load_profile(str(profile_dir))
    profile_service.invalidate_profile_cache()
    with pytest.raises(RuntimeError):
        profile_service.get_profile()


def test_load_profile_missing_file_raises(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with pytest.raises(FileNotFoundError):
        profile_service.load_profile(str(empty_dir))
