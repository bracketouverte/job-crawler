import json
from pathlib import Path

import post_crawl


def _write_report(path: Path, failures: list[dict]) -> None:
    path.write_text(json.dumps({"failures": failures}))


def test_run_adds_404_and_410_failures(tmp_path):
    report_path = tmp_path / "report.json"
    _write_report(
        report_path,
        [
            {"provider": "lever", "source_key": "gone", "status": 404, "message": "x"},
            {"provider": "ashby", "source_key": "also-gone", "status": 410, "message": "x"},
        ],
    )
    exclude_path = tmp_path / "exclude.jsonl"

    added = post_crawl.run(str(report_path), str(exclude_path))

    lines = [json.loads(line) for line in exclude_path.read_text().splitlines() if line.strip()]
    assert added == 2
    assert {(line["provider"], line["source_key"]) for line in lines} == {
        ("lever", "gone"),
        ("ashby", "also-gone"),
    }
    assert all(line["reason"] == "http_404" for line in lines)


def test_run_ignores_non_404_410_statuses(tmp_path):
    report_path = tmp_path / "report.json"
    _write_report(report_path, [{"provider": "lever", "source_key": "broken", "status": 500, "message": "x"}])
    exclude_path = tmp_path / "exclude.jsonl"

    added = post_crawl.run(str(report_path), str(exclude_path))

    assert added == 0
    assert exclude_path.read_text() == ""


def test_run_twice_does_not_duplicate(tmp_path):
    report_path = tmp_path / "report.json"
    _write_report(report_path, [{"provider": "lever", "source_key": "gone", "status": 404, "message": "x"}])
    exclude_path = tmp_path / "exclude.jsonl"

    post_crawl.run(str(report_path), str(exclude_path))
    added_second = post_crawl.run(str(report_path), str(exclude_path))

    lines = [line for line in exclude_path.read_text().splitlines() if line.strip()]
    assert added_second == 0
    assert len(lines) == 1


def test_run_creates_exclude_file_if_missing(tmp_path):
    report_path = tmp_path / "report.json"
    _write_report(report_path, [])
    exclude_path = tmp_path / "state" / "exclude.jsonl"

    post_crawl.run(str(report_path), str(exclude_path))

    assert exclude_path.exists()


def test_run_appends_across_multiple_crawl_runs_stays_valid_jsonl(tmp_path):
    exclude_path = tmp_path / "exclude.jsonl"
    report1 = tmp_path / "report1.json"
    _write_report(report1, [{"provider": "lever", "source_key": "a", "status": 404, "message": "x"}])
    post_crawl.run(str(report1), str(exclude_path))

    report2 = tmp_path / "report2.json"
    _write_report(report2, [{"provider": "lever", "source_key": "b", "status": 410, "message": "x"}])
    post_crawl.run(str(report2), str(exclude_path))

    lines = [json.loads(line) for line in exclude_path.read_text().splitlines() if line.strip()]
    assert len(lines) == 2
    assert {line["source_key"] for line in lines} == {"a", "b"}
