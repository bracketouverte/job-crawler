"""Story 14.1 — HTTP Round-Trip Test.

Verifies parse -> score -> persist end-to-end through the real
POST /api/match-runs router, against a real catalog_jobs row, with the
matcher_client HTTP calls mocked at the network boundary (matcher_client.
parse_batch / matcher_client.analyze) in place of live LLM calls -- this
test is about proving the pipeline's wiring is correct, not about LLM
output quality, matching the story's own acceptance criterion ("Analysis
round-trip works end-to-end via HTTP").

Supersedes the old subprocess-backed test_subprocess_roundtrip.py, which
verified the same contract against the (now removed) subprocess transport.
"""

import json
import time

import pytest

from services import matcher_client
from tests.conftest import insert_job


async def _fake_parse_batch(urls):
    parsed = {"title": "Parsed Title", "location": "Remote", "provider": "greenhouse"}
    return [{"url": u, "parsed": parsed, "parse_error": None} for u in urls]


async def _fake_analyze(mode, jobs, run_id):
    return [
        {
            "status": "ok",
            "provider": j["provider"],
            "source_key": j["source_key"],
            "job_id": j["job_id"],
            "analysis": {"score_5": 4.5, "pipeline": mode},
        }
        for j in jobs
    ]


@pytest.fixture
def env(migrated_env, monkeypatch):
    monkeypatch.setattr(matcher_client, "parse_batch", _fake_parse_batch)
    monkeypatch.setattr(matcher_client, "analyze", _fake_analyze)
    return migrated_env


def _wait_for_completion(client, run_id, timeout_s=30):
    deadline = time.time() + timeout_s
    manifest = None
    while time.time() < deadline:
        manifest = client.get(f"/api/match-runs/{run_id}").json()
        if manifest["status"] in ("completed", "failed"):
            return manifest
        time.sleep(0.05)
    return manifest


def test_full_round_trip_parse_score_persist(app_client, env):
    insert_job(
        env["catalog_db"],
        provider="greenhouse",
        source_key="acme",
        job_id="1",
        title="Backend Engineer",
        job_url="https://example.com/job/1",
    )

    r = app_client.post("/api/match-runs", json={"job_keys": ["greenhouse|acme|1"], "mode": "claude"})
    assert r.status_code == 202
    run_id = r.json()["run_id"]

    started = time.time()
    manifest = _wait_for_completion(app_client, run_id, timeout_s=30)
    elapsed = time.time() - started

    assert elapsed < 30, f"round trip took {elapsed:.1f}s"
    assert manifest["status"] == "completed", manifest

    # analysis_score is written to catalog_jobs after completion
    row = fetchone_sync(env["catalog_db"], "greenhouse", "acme", "1")
    assert row["analysis_score"] == 4.5

    # parsed_jd is populated after the parse phase
    assert row["parsed_jd"] is not None
    parsed = json.loads(row["parsed_jd"])
    assert parsed["title"] == "Parsed Title"

    # results.jsonl exists with at least one status: "ok" row, and its
    # pipeline tag has been relabeled to the viewer's own mode convention
    from services.match_run import match_run_results_path

    results_text = match_run_results_path(run_id).read_text()
    results = [json.loads(line) for line in results_text.splitlines() if line.strip()]
    assert any(r["status"] == "ok" for r in results)
    assert results[0]["analysis"]["pipeline"] == "claude"

    # GET /api/job reflects the same analysis
    job = app_client.get(
        "/api/job", params={"provider": "greenhouse", "source_key": "acme", "job_id": "1"}
    ).json()
    assert job["analysis"]["score_5"] == 4.5


def fetchone_sync(catalog_db, provider, source_key, job_id):
    import sqlite3

    conn = sqlite3.connect(str(catalog_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT analysis_score, parsed_jd FROM catalog_jobs "
        "WHERE provider = ? AND source_key = ? AND job_id = ?",
        (provider, source_key, job_id),
    ).fetchone()
    conn.close()
    return row
