import json
from datetime import UTC, datetime, timedelta

import dead_slugs


def test_load_dead_slugs_missing_file_returns_empty_set(tmp_path):
    assert dead_slugs.load_dead_slugs(str(tmp_path), "greenhouse") == set()


def test_mark_dead_only_for_404_410(tmp_path):
    dead_slugs.mark_dead(str(tmp_path), "greenhouse", "acme", 500)
    assert dead_slugs.load_dead_slugs(str(tmp_path), "greenhouse") == set()

    dead_slugs.mark_dead(str(tmp_path), "greenhouse", "acme", 404)
    assert dead_slugs.load_dead_slugs(str(tmp_path), "greenhouse") == {"acme"}


def test_mark_dead_410_also_quarantines(tmp_path):
    dead_slugs.mark_dead(str(tmp_path), "greenhouse", "beta", 410)
    assert dead_slugs.load_dead_slugs(str(tmp_path), "greenhouse") == {"beta"}


def test_expired_entry_is_pruned_on_load(tmp_path):
    path = dead_slugs._file_path(str(tmp_path), "greenhouse")
    stale = {
        "old-slug": {
            "deadAt": (datetime.now(UTC) - timedelta(days=20)).isoformat().replace("+00:00", "Z"),
            "code": 404,
            "ttlDays": 5,
        }
    }
    path.write_text(json.dumps(stale))

    assert dead_slugs.load_dead_slugs(str(tmp_path), "greenhouse") == set()
    # Pruning also persists back to disk.
    assert json.loads(path.read_text()) == {}


def test_non_expired_entry_survives_load(tmp_path):
    path = dead_slugs._file_path(str(tmp_path), "greenhouse")
    fresh = {
        "fresh-slug": {
            "deadAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "code": 404,
            "ttlDays": 10,
        }
    }
    path.write_text(json.dumps(fresh))

    assert dead_slugs.load_dead_slugs(str(tmp_path), "greenhouse") == {"fresh-slug"}


def test_random_ttl_is_within_3_to_10_days_inclusive():
    for _ in range(50):
        ttl = dead_slugs._random_ttl_days()
        assert 3 <= ttl <= 10


def test_different_providers_use_separate_files(tmp_path):
    dead_slugs.mark_dead(str(tmp_path), "greenhouse", "acme", 404)
    dead_slugs.mark_dead(str(tmp_path), "lever", "acme", 404)

    assert dead_slugs.load_dead_slugs(str(tmp_path), "greenhouse") == {"acme"}
    assert dead_slugs.load_dead_slugs(str(tmp_path), "lever") == {"acme"}
    assert dead_slugs._file_path(str(tmp_path), "greenhouse") != dead_slugs._file_path(str(tmp_path), "lever")
