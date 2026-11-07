import json
import re

import pytest

from services import match_run as mr
from services import matcher_client, queue_store
from tests.conftest import insert_job

pytestmark = pytest.mark.usefixtures("isolated_env")


def test_generate_run_id_matches_expected_format():
    run_id = mr.generate_run_id()
    assert re.fullmatch(r"run_\d{14}_[a-z0-9]{6}", run_id)


def test_match_run_paths(isolated_env):
    run_id = "run_x"
    d = mr.match_run_dir(run_id)
    assert mr.match_run_manifest_path(run_id) == d / "manifest.json"
    assert mr.match_run_input_path(run_id) == d / "jobs.jsonl"
    assert mr.match_run_results_path(run_id) == d / "results.jsonl"
    assert mr.match_run_log_path(run_id) == d / "matcher.log"


async def test_write_and_read_manifest_round_trip():
    manifest = {"id": "run_1", "status": "pending"}
    await mr.write_manifest("run_1", manifest)
    assert await mr.read_manifest("run_1") == manifest

    raw = mr.match_run_manifest_path("run_1").read_text()
    assert raw.endswith("\n")
    assert raw.startswith("{\n")  # indent=2 pretty-printed


async def test_read_manifest_missing_returns_none():
    assert await mr.read_manifest("does-not-exist") is None


async def test_mark_orphaned_runs_failed_flips_running_manifest():
    await mr.write_manifest("run_a", {"id": "run_a", "status": "running"})
    await mr.write_manifest("run_b", {"id": "run_b", "status": "completed"})
    await mr.mark_orphaned_runs_failed()
    a = await mr.read_manifest("run_a")
    b = await mr.read_manifest("run_b")
    assert a["status"] == "failed"
    assert a["error"] == "orphaned: server restarted"
    assert b["status"] == "completed"  # untouched


async def test_mark_orphaned_runs_failed_flips_stuck_queue_items():
    await queue_store.upsert_queue_item(
        {
            "id": "run_a:x|y|1",
            "status": "running",
            "subtasks": [{"id": "discord", "status": "running"}],
        }
    )
    await queue_store.upsert_queue_item(
        {
            "id": "run_a:x|y|2",
            "status": "todo",
            "subtasks": [{"id": "discord", "status": "todo"}],
        }
    )
    await queue_store.upsert_queue_item(
        {
            "id": "run_a:x|y|3",
            "status": "done",
            "subtasks": [{"id": "discord", "status": "done"}],
        }
    )
    await mr.mark_orphaned_runs_failed()
    items = {i["id"]: i for i in await queue_store.read_queue()}
    assert items["run_a:x|y|1"]["status"] == "permanent_error"
    assert items["run_a:x|y|1"]["subtasks"][0]["status"] == "error"
    assert items["run_a:x|y|2"]["status"] == "permanent_error"
    assert items["run_a:x|y|3"]["status"] == "done"  # untouched


async def test_append_match_run_log_writes_prefixed_line():
    mr.match_run_dir("run_1").mkdir(parents=True, exist_ok=True)
    await mr.append_match_run_log("run_1", "hello", stream="stdout")
    text = mr.match_run_log_path("run_1").read_text()
    assert text == "[match-run run_1] stdout: hello\n"


def test_clean_parsed_text_collapses_whitespace_and_strips():
    assert mr.clean_parsed_text("  a   b\n c ") == "a b c"


def test_clean_parsed_text_empty_is_none():
    assert mr.clean_parsed_text("   ") is None
    assert mr.clean_parsed_text(None) is None


async def test_persist_parsed_metadata_fills_empty_location_only(isolated_env):
    insert_job(isolated_env["catalog_db"], provider="gh", source_key="acme", job_id="1", location="")
    job = {"provider": "gh", "source_key": "acme", "job_id": "1"}
    await mr.persist_parsed_metadata(job, {"location": "Miami, FL"})

    from db import fetchall

    row = (await fetchall("SELECT location FROM catalog_jobs WHERE job_id = '1'"))[0]
    assert row["location"] == "Miami, FL"


async def test_persist_parsed_metadata_does_not_overwrite_existing_location(isolated_env):
    insert_job(isolated_env["catalog_db"], provider="gh", source_key="acme", job_id="1", location="Existing")
    job = {"provider": "gh", "source_key": "acme", "job_id": "1"}
    await mr.persist_parsed_metadata(job, {"location": "Miami, FL"})

    from db import fetchall

    row = (await fetchall("SELECT location FROM catalog_jobs WHERE job_id = '1'"))[0]
    assert row["location"] == "Existing"


async def test_persist_parsed_metadata_always_overwrites_compensation(isolated_env):
    insert_job(
        isolated_env["catalog_db"], provider="gh", source_key="acme", job_id="1", compensation="$50k-$60k"
    )
    job = {"provider": "gh", "source_key": "acme", "job_id": "1"}
    await mr.persist_parsed_metadata(job, {"compensation": "$100k-$120k"})

    from db import fetchall

    row = (await fetchall("SELECT compensation FROM catalog_jobs WHERE job_id = '1'"))[0]
    assert row["compensation"] == "$100k-$120k"


def test_build_jd_text_includes_sections_and_omits_empty():
    parsed = {
        "title": "Backend Engineer",
        "location": "Remote",
        "responsibilities": ["Ship code"],
        "must_have_requirements": ["5+ years Python"],
    }
    job = {"provider": "greenhouse", "source_key": "acme", "title": "Backend Engineer"}
    text = mr.build_jd_text(parsed, job)
    assert "Title: Backend Engineer" in text
    assert "Responsibilities:\n- Ship code" in text
    assert "Requirements:\n- 5+ years Python" in text
    assert "Nice-to-have" not in text


async def test_read_input_lines_missing_file_returns_empty():
    assert await mr.read_input_lines("nope") == []


async def test_read_results_jsonl_missing_file_returns_empty():
    assert await mr.read_results_jsonl("nope") == []


async def test_read_results_jsonl_skips_malformed_lines(isolated_env):
    path = mr.match_run_results_path("run_1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"a": 1}\nnot json\n{"b": 2}\n')
    results = await mr.read_results_jsonl("run_1")
    assert results == [{"a": 1}, {"b": 2}]


async def test_cancel_run_delegates_to_matcher_client(monkeypatch):
    calls = []

    async def fake_cancel(run_id):
        calls.append(run_id)
        return True

    monkeypatch.setattr(matcher_client, "cancel_run", fake_cancel)
    assert await mr.cancel_run("run_1") is True
    assert calls == ["run_1"]


# --- HTTP-backed integration tests (matcher_client mocked at the network
# boundary) --------------------------------------------------------------


async def test_write_batch_input_skips_cached_and_missing_url(isolated_env, monkeypatch):
    async def fake_parse_batch(urls):
        assert urls == ["https://example.com/ok"] * 3
        return [{"url": u, "parsed": {"title": "Parsed Title"}, "parse_error": None} for u in urls]

    monkeypatch.setattr(matcher_client, "parse_batch", fake_parse_batch)

    jobs = [
        {
            "provider": "gh",
            "source_key": "acme",
            "job_id": str(i),
            "title": f"Job {i}",
            "job_url": "https://example.com/ok",
        }
        for i in range(3)
    ]
    jobs.append(
        {
            "provider": "gh",
            "source_key": "acme",
            "job_id": "cached",
            "title": "Cached",
            "parsed_jd": json.dumps({"title": "Already parsed"}),
        }
    )
    jobs.append({"provider": "gh", "source_key": "acme", "job_id": "nourl", "title": "No URL"})

    mr.match_run_dir("run_1").mkdir(parents=True, exist_ok=True)
    manifest = await mr.write_batch_input("run_1", jobs, {"id": "run_1"})
    assert manifest["parsed_count"] == 4  # 3 parsed + 1 cached; nourl fails

    lines = mr.match_run_input_path("run_1").read_text().splitlines()
    assert len(lines) == 5
    parsed_lines = [json.loads(line) for line in lines]
    nourl = next(line for line in parsed_lines if line["job_id"] == "nourl")
    assert nourl["parse_error"] == "Missing job URL"
    cached = next(line for line in parsed_lines if line["job_id"] == "cached")
    assert cached["parse_error"] is None
    assert cached["title"] == "Already parsed"


async def test_write_batch_input_surfaces_matcher_parse_error(isolated_env, monkeypatch):
    async def fake_parse_batch(urls):
        return [{"url": urls[0], "parsed": None, "parse_error": "Unsupported provider"}]

    monkeypatch.setattr(matcher_client, "parse_batch", fake_parse_batch)

    jobs = [{"provider": "gh", "source_key": "acme", "job_id": "1", "job_url": "https://example.com/fail"}]
    mr.match_run_dir("run_1").mkdir(parents=True, exist_ok=True)
    manifest = await mr.write_batch_input("run_1", jobs, {"id": "run_1"})
    assert manifest["parsed_count"] == 0

    line = json.loads(mr.match_run_input_path("run_1").read_text().splitlines()[0])
    assert line["parse_error"] == "Unsupported provider"


async def test_write_batch_input_handles_matcher_call_failure(isolated_env, monkeypatch):
    async def failing_parse_batch(urls):
        raise RuntimeError("matcher unreachable")

    monkeypatch.setattr(matcher_client, "parse_batch", failing_parse_batch)

    jobs = [{"provider": "gh", "source_key": "acme", "job_id": "1", "job_url": "https://example.com/x"}]
    mr.match_run_dir("run_1").mkdir(parents=True, exist_ok=True)
    manifest = await mr.write_batch_input("run_1", jobs, {"id": "run_1"})
    assert manifest["parsed_count"] == 0

    line = json.loads(mr.match_run_input_path("run_1").read_text().splitlines()[0])
    assert line["parse_error"] == "No parse result returned"


async def test_run_scorer_phase_success_relabels_pipeline(isolated_env, monkeypatch):
    mr.match_run_input_path("run_1").parent.mkdir(parents=True, exist_ok=True)
    job_line = json.dumps(
        {"provider": "gh", "source_key": "acme", "job_id": "1", "title": "Backend", "company": "acme"}
    )
    mr.match_run_input_path("run_1").write_text(job_line + "\n")

    async def fake_analyze(mode, jobs, run_id):
        assert mode == "claude-ensemble"
        assert run_id == "run_1"
        return [
            {
                "status": "ok",
                "provider": "gh",
                "source_key": "acme",
                "job_id": "1",
                "analysis": {"score_5": 4.5, "pipeline": "ensemble"},
            }
        ]

    monkeypatch.setattr(matcher_client, "analyze", fake_analyze)

    queue_items = [
        {
            "id": "run_1:gh|acme|1",
            "title": "Backend",
            "company": "acme",
            "subtasks": queue_store.build_subtasks("claude-ensemble"),
        }
    ]
    results = await mr.run_scorer_phase("run_1", "claude-ensemble", queue_items)
    assert results[0]["status"] == "ok"
    # Relabeled from matcher's own "ensemble" tag to the viewer's mode convention.
    assert results[0]["analysis"]["pipeline"] == "claude-ensemble"
    log_text = mr.match_run_log_path("run_1").read_text()
    assert "[score] start" in log_text
    assert "[score] done" in log_text


async def test_run_scorer_phase_all_error_raises(isolated_env, monkeypatch):
    mr.match_run_input_path("run_1").parent.mkdir(parents=True, exist_ok=True)
    job_line = json.dumps(
        {"provider": "gh", "source_key": "acme", "job_id": "1", "title": "Backend", "company": "acme"}
    )
    mr.match_run_input_path("run_1").write_text(job_line + "\n")

    async def fake_analyze(mode, jobs, run_id):
        return [{"status": "error", "provider": "gh", "source_key": "acme", "job_id": "1", "error": "forced"}]

    monkeypatch.setattr(matcher_client, "analyze", fake_analyze)

    queue_items = [
        {
            "id": "run_1:gh|acme|1",
            "title": "Backend",
            "company": "acme",
            "subtasks": queue_store.build_subtasks("claude-ensemble"),
        }
    ]
    with pytest.raises(RuntimeError, match="forced"):
        await mr.run_scorer_phase("run_1", "claude-ensemble", queue_items)


async def test_run_scorer_phase_matcher_call_failure_raises(isolated_env, monkeypatch):
    mr.match_run_input_path("run_1").parent.mkdir(parents=True, exist_ok=True)
    mr.match_run_input_path("run_1").write_text("{}\n")

    async def failing_analyze(mode, jobs, run_id):
        raise RuntimeError("matcher unreachable")

    monkeypatch.setattr(matcher_client, "analyze", failing_analyze)

    with pytest.raises(RuntimeError, match="matcher unreachable"):
        await mr.run_scorer_phase("run_1", "claude", [])


async def test_run_scorer_phase_empty_message_error_names_exception_type(isolated_env, monkeypatch):
    import httpx

    mr.match_run_input_path("run_1").parent.mkdir(parents=True, exist_ok=True)
    mr.match_run_input_path("run_1").write_text("{}\n")

    async def timing_out_analyze(mode, jobs, run_id):
        raise httpx.ReadTimeout("")

    monkeypatch.setattr(matcher_client, "analyze", timing_out_analyze)

    with pytest.raises(RuntimeError, match="ReadTimeout"):
        await mr.run_scorer_phase("run_1", "claude", [])


async def test_execute_match_run_marks_manifest_failed_when_setup_raises(isolated_env, monkeypatch):
    await mr.write_manifest("run_x", {"id": "run_x", "status": "pending"})

    async def boom(run_id, jobs, manifest):
        raise OSError("disk full")

    monkeypatch.setattr(mr, "write_batch_input", boom)

    await mr.execute_match_run("run_x", [{"provider": "p", "source_key": "s", "job_id": "1"}], "claude")

    manifest = await mr.read_manifest("run_x")
    assert manifest["status"] == "failed"
    assert "disk full" in manifest["error"]
    assert "run_x" not in mr.active_run_ids


@pytest.fixture
def mocked_matcher(monkeypatch):
    async def fake_parse_batch(urls):
        return [{"url": u, "parsed": {"title": "Parsed"}, "parse_error": None} for u in urls]

    async def fake_analyze(mode, jobs, run_id):
        results = []
        for job in jobs:
            if job.get("_force_error"):
                results.append(
                    {
                        "status": "error",
                        "provider": job["provider"],
                        "source_key": job["source_key"],
                        "job_id": job["job_id"],
                        "error": "forced failure",
                    }
                )
            else:
                results.append(
                    {
                        "status": "ok",
                        "provider": job["provider"],
                        "source_key": job["source_key"],
                        "job_id": job["job_id"],
                        "analysis": {"score_5": 4.5, "pipeline": "ensemble"},
                    }
                )
        return results

    monkeypatch.setattr(matcher_client, "parse_batch", fake_parse_batch)
    monkeypatch.setattr(matcher_client, "analyze", fake_analyze)


async def test_execute_match_run_from_input_end_to_end(mocked_matcher, migrated_env):
    run_id = "run_e2e"
    await mr.write_manifest(
        run_id,
        {
            "id": run_id,
            "status": "pending",
            "mode": "claude-ensemble",
            "job_count": 1,
            "parsed_count": 0,
            "matched_count": 0,
            "created_at": "x",
            "updated_at": "x",
            "error": None,
        },
    )
    line = json.dumps(
        {"provider": "gh", "source_key": "acme", "job_id": "1", "title": "Backend", "company": "acme"}
    )

    await mr.execute_match_run_from_input(run_id, [line], "claude-ensemble")

    manifest = await mr.read_manifest(run_id)
    assert manifest["status"] == "completed"
    assert manifest["matched_count"] == 1
    assert run_id not in mr.active_run_ids

    items = await queue_store.read_queue()
    assert items[0]["status"] == "done"
    assert all(s["status"] == "done" for s in items[0]["subtasks"])


async def test_execute_match_run_partial_failure_does_not_raise(mocked_matcher, migrated_env):
    run_id = "run_partial"
    await mr.write_manifest(
        run_id,
        {
            "id": run_id,
            "status": "pending",
            "mode": "claude-ensemble",
            "job_count": 2,
            "parsed_count": 0,
            "matched_count": 0,
            "created_at": "x",
            "updated_at": "x",
            "error": None,
        },
    )
    ok_line = json.dumps(
        {"provider": "gh", "source_key": "acme", "job_id": "1", "title": "OK", "company": "acme"}
    )
    err_line = json.dumps(
        {
            "provider": "gh",
            "source_key": "acme",
            "job_id": "2",
            "title": "Err",
            "company": "acme",
            "_force_error": True,
        }
    )

    await mr.execute_match_run_from_input(run_id, [ok_line, err_line], "claude-ensemble")
    manifest = await mr.read_manifest(run_id)
    assert manifest["status"] == "completed"
    assert manifest["matched_count"] == 1


async def test_execute_match_run_all_error_flips_manifest_failed(mocked_matcher, isolated_env):
    run_id = "run_allerr"
    await mr.write_manifest(
        run_id,
        {
            "id": run_id,
            "status": "pending",
            "mode": "claude-ensemble",
            "job_count": 1,
            "parsed_count": 0,
            "matched_count": 0,
            "created_at": "x",
            "updated_at": "x",
            "error": None,
        },
    )
    err_line = json.dumps(
        {
            "provider": "gh",
            "source_key": "acme",
            "job_id": "1",
            "title": "Err",
            "company": "acme",
            "_force_error": True,
        }
    )

    await mr.execute_match_run_from_input(run_id, [err_line], "claude-ensemble")
    manifest = await mr.read_manifest(run_id)
    assert manifest["status"] == "failed"

    items = await queue_store.read_queue()
    assert items[0]["status"] == "retrying"
    assert items[0]["attempt"] == 2


async def test_execute_match_run_missing_manifest_is_noop(mocked_matcher):
    await mr.execute_match_run_from_input("does-not-exist", ["{}"], "claude")
    assert await mr.read_manifest("does-not-exist") is None


async def test_execute_match_run_end_to_end_with_parse_phase(mocked_matcher, migrated_env):
    run_id = "run_full"
    await mr.write_manifest(
        run_id,
        {
            "id": run_id,
            "status": "pending",
            "mode": "claude",
            "job_count": 1,
            "parsed_count": 0,
            "matched_count": 0,
            "created_at": "x",
            "updated_at": "x",
            "error": None,
        },
    )
    jobs = [
        {
            "provider": "gh",
            "source_key": "acme",
            "job_id": "1",
            "title": "Backend",
            "job_url": "https://example.com/1",
        }
    ]

    await mr.execute_match_run(run_id, jobs, "claude")

    manifest = await mr.read_manifest(run_id)
    assert manifest["status"] == "completed"
    assert manifest["parsed_count"] == 1
    assert manifest["matched_count"] == 1


async def test_write_manifest_failure_keeps_previous_manifest_readable():
    await mr.write_manifest("run_atomic", {"id": "run_atomic", "status": "running"})

    with pytest.raises(TypeError):
        await mr.write_manifest("run_atomic", {"id": "run_atomic", "status": object()})

    assert await mr.read_manifest("run_atomic") == {"id": "run_atomic", "status": "running"}
