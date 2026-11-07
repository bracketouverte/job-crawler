import json
import sqlite3

import pytest

import trend_log


def _make_catalog_db(path) -> None:
    db = sqlite3.connect(str(path))
    db.execute("CREATE TABLE catalog_jobs (provider TEXT, source_key TEXT, job_id TEXT, skill_tier TEXT)")
    db.executemany(
        "INSERT INTO catalog_jobs (provider, source_key, job_id, skill_tier) VALUES (?, ?, ?, ?)",
        [
            ("lever", "a", "1", "senior"),
            ("lever", "a", "2", "mid"),
            ("ashby", "b", "1", None),
        ],
    )
    db.commit()
    db.close()


def test_append_trend_entry_writes_expected_shape(tmp_path):
    db_path = tmp_path / "catalog.sqlite"
    _make_catalog_db(db_path)

    trend_log.append_trend_entry(str(db_path), str(tmp_path))

    lines = (tmp_path / "trends.jsonl").read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["total"] == 3
    assert entry["by_provider"] == {"lever": 2, "ashby": 1}
    assert entry["by_tier"] == {"senior": 1, "mid": 1}
    assert "date" in entry


def test_append_trend_entry_appends_not_overwrites(tmp_path):
    db_path = tmp_path / "catalog.sqlite"
    _make_catalog_db(db_path)

    trend_log.append_trend_entry(str(db_path), str(tmp_path))
    trend_log.append_trend_entry(str(db_path), str(tmp_path))

    lines = (tmp_path / "trends.jsonl").read_text().splitlines()
    assert len(lines) == 2


def test_append_trend_entry_raises_for_missing_db(tmp_path):
    with pytest.raises(sqlite3.OperationalError):
        trend_log.append_trend_entry(str(tmp_path / "missing.sqlite"), str(tmp_path))
