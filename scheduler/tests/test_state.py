import json
from datetime import UTC, datetime, timedelta

import config
import state


def test_read_runs_missing_file_returns_empty(runs_file):
    assert state.read_runs() == []


def test_read_runs_corrupted_file_returns_empty(runs_file):
    runs_file.write_text("not json")
    assert state.read_runs() == []


def test_read_runs_non_list_json_returns_empty(runs_file):
    runs_file.write_text(json.dumps({"not": "a list"}))
    assert state.read_runs() == []


def test_record_run_appends_and_persists(runs_file):
    state.record_run("2026-01-01T08:00:00Z")
    assert state.read_runs() == ["2026-01-01T08:00:00Z"]
    state.record_run("2026-01-01T10:00:00Z")
    assert state.read_runs() == ["2026-01-01T08:00:00Z", "2026-01-01T10:00:00Z"]


def test_record_run_writes_atomically_via_tmp_rename(runs_file):
    state.record_run("2026-01-01T08:00:00Z")
    assert runs_file.exists()
    assert not runs_file.with_name(f"{runs_file.name}.tmp").exists()


def test_record_run_creates_parent_directory(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "scheduler-runs.json"
    monkeypatch.setattr(config, "RUNS_FILE", str(path))
    state.record_run("2026-01-01T08:00:00Z")
    assert path.exists()


def test_record_run_caps_history_at_max_runs(runs_file, monkeypatch):
    monkeypatch.setattr(config, "MAX_RUNS_HISTORY", 3)
    for i in range(5):
        state.record_run(f"2026-01-0{i + 1}T08:00:00Z")
    runs = state.read_runs()
    assert len(runs) == 3
    assert runs == ["2026-01-03T08:00:00Z", "2026-01-04T08:00:00Z", "2026-01-05T08:00:00Z"]


def test_last_run_at_returns_most_recent_parsed_timestamp(runs_file):
    state.record_run("2026-01-01T08:00:00Z")
    state.record_run("2026-01-01T10:00:00Z")
    assert state.last_run_at() == datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)


def test_last_run_at_no_runs_returns_none(runs_file):
    assert state.last_run_at() is None


def test_last_run_at_invalid_timestamp_returns_none(runs_file):
    runs_file.write_text(json.dumps(["not-a-timestamp"]))
    assert state.last_run_at() is None


def test_is_debounced_true_when_last_run_100_minutes_ago(runs_file):
    ts = (datetime.now(UTC) - timedelta(minutes=100)).strftime("%Y-%m-%dT%H:%M:%SZ")
    state.record_run(ts)
    assert state.is_debounced() is True


def test_is_debounced_false_when_last_run_120_minutes_ago(runs_file):
    ts = (datetime.now(UTC) - timedelta(minutes=120)).strftime("%Y-%m-%dT%H:%M:%SZ")
    state.record_run(ts)
    assert state.is_debounced() is False


def test_is_debounced_false_when_never_run(runs_file):
    assert state.is_debounced() is False
