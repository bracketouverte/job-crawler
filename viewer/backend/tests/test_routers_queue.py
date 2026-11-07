import time

import pytest

from services import matcher_client
from tests.conftest import insert_job


async def _fake_parse_batch(urls):
    return [{"url": u, "parsed": {"title": "Parsed"}, "parse_error": None} for u in urls]


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


async def _slow_analyze(mode, jobs, run_id):
    import asyncio

    await asyncio.sleep(5)
    return []


@pytest.fixture
def env_with_matcher(migrated_env, monkeypatch):
    monkeypatch.setattr(matcher_client, "parse_batch", _fake_parse_batch)
    monkeypatch.setattr(matcher_client, "analyze", _fake_analyze)
    return migrated_env


def _wait_for(predicate, timeout=10):
    deadline = time.time() + timeout
    result = None
    while time.time() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.05)
    return result


def test_get_queue_empty(app_client):
    r = app_client.get("/api/queue")
    assert r.status_code == 200
    assert r.json() == []


def test_retry_not_found(app_client):
    r = app_client.post("/api/queue/does-not-exist/retry")
    assert r.status_code == 404


def _seed_queue_file(state_dir, items):
    """Writes directly to the queue JSON file instead of going through
    queue_store's asyncio.Lock — that lock binds to whichever event loop
    first acquires it, and TestClient runs the app (and thus queue_store)
    on its own portal-thread loop, so awaiting queue_store from the test's
    own loop in the same test would crash with a cross-loop error."""
    import json

    (state_dir / "retry-queue.json").write_text(json.dumps(items))


def test_retry_discord_only_does_not_rerun_analysis(app_client, migrated_env):
    import json

    item_id = "discord_x"
    row = {"provider": "gh", "source_key": "acme", "job_id": "1"}
    _seed_queue_file(
        migrated_env["state_dir"],
        [
            {
                "id": item_id,
                "job_key": "gh|acme|1",
                "mode": "discord-only",
                "status": "retrying",
                "subtasks": [{"id": "discord", "status": "error"}],
                "attempt": 1,
                "max_attempts": 3,
                "created_at": "x",
                "updated_at": "x",
                "error": json.dumps(row),
                "next_retry_at": None,
            }
        ],
    )
    r = app_client.post(f"/api/queue/{item_id}/retry")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "retrying"
    assert body["next_retry_at"] is not None


def test_retry_normal_item_resets_attempt_and_reruns(app_client, env_with_matcher):
    insert_job(env_with_matcher["catalog_db"], provider="gh", source_key="acme", job_id="1")
    r = app_client.post("/api/match-runs", json={"job_keys": ["gh|acme|1"], "mode": "claude"})
    run_id = r.json()["run_id"]
    item_id = f"{run_id}:gh|acme|1"

    _wait_for(
        lambda: app_client.get("/api/queue").json()
        and app_client.get("/api/queue").json()[0]["status"] == "done"
    )

    rr = app_client.post(f"/api/queue/{item_id}/retry")
    assert rr.status_code == 200
    assert rr.json()["attempt"] == 0

    _wait_for(lambda: app_client.get("/api/queue").json()[0]["status"] == "done")
    final = app_client.get("/api/queue").json()[0]
    assert final["status"] == "done"


def test_stop_cancels_matcher_run_and_flips_manifest(app_client, migrated_env, monkeypatch):
    cancelled = []

    async def fake_cancel_run(run_id):
        cancelled.append(run_id)
        return True

    monkeypatch.setattr(matcher_client, "parse_batch", _fake_parse_batch)
    monkeypatch.setattr(matcher_client, "analyze", _slow_analyze)
    monkeypatch.setattr(matcher_client, "cancel_run", fake_cancel_run)
    insert_job(migrated_env["catalog_db"], provider="gh", source_key="acme", job_id="1")
    r = app_client.post("/api/match-runs", json={"job_keys": ["gh|acme|1"], "mode": "claude"})
    run_id = r.json()["run_id"]
    item_id = f"{run_id}:gh|acme|1"

    _wait_for(lambda: app_client.get("/api/queue").json())

    sr = app_client.post(f"/api/queue/{item_id}/stop")
    assert sr.status_code == 200
    assert sr.json()["status"] == "permanent_error"
    assert cancelled == [run_id]

    manifest = app_client.get(f"/api/match-runs/{run_id}").json()
    assert manifest["status"] in ("failed", "running", "completed")


def test_restart_resets_created_at(app_client, env_with_matcher):
    insert_job(env_with_matcher["catalog_db"], provider="gh", source_key="acme", job_id="1")
    r = app_client.post("/api/match-runs", json={"job_keys": ["gh|acme|1"], "mode": "claude"})
    run_id = r.json()["run_id"]
    item_id = f"{run_id}:gh|acme|1"

    _wait_for(
        lambda: app_client.get("/api/queue").json()
        and app_client.get("/api/queue").json()[0]["status"] == "done"
    )
    original = app_client.get("/api/queue").json()[0]

    rr = app_client.post(f"/api/queue/{item_id}/restart")
    assert rr.status_code == 200
    assert rr.json()["attempt"] == 1
    assert rr.json()["created_at"] != original["created_at"]

    _wait_for(lambda: app_client.get("/api/queue").json()[0]["status"] == "done")


def test_delete_removes_item(app_client, migrated_env):
    _seed_queue_file(migrated_env["state_dir"], [{"id": "x", "status": "done"}])
    r = app_client.delete("/api/queue/x")
    assert r.status_code == 200
    assert app_client.get("/api/queue").json() == []
