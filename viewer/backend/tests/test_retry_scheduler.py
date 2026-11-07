import json

import pytest

import config
from services import match_run as mr
from services import matcher_client, queue_store, retry_scheduler


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


@pytest.fixture
def env(migrated_env, monkeypatch):
    async def fake_analyze(mode, jobs, run_id):
        return [
            {
                "status": "ok",
                "provider": j["provider"],
                "source_key": j["source_key"],
                "job_id": j["job_id"],
                "analysis": {"score_5": 4.5, "pipeline": "ensemble"},
            }
            for j in jobs
        ]

    monkeypatch.setattr(matcher_client, "analyze", fake_analyze)
    return migrated_env


async def test_tick_skips_items_not_due(env):
    await queue_store.upsert_queue_item(
        {
            "id": "run_1:x|y|1",
            "status": "retrying",
            "next_retry_at": "2099-01-01T00:00:00Z",
            "subtasks": [{"id": "model:claude"}, {"id": "discord"}],
            "mode": "claude",
            "attempt": 1,
            "max_attempts": 3,
        }
    )
    await retry_scheduler._tick()
    item = (await queue_store.read_queue())[0]
    assert item["status"] == "retrying"


async def test_tick_ignores_non_retrying_items(env):
    await queue_store.upsert_queue_item({"id": "a", "status": "done"})
    await retry_scheduler._tick()  # should not raise
    assert (await queue_store.read_queue())[0]["status"] == "done"


async def test_tick_reruns_due_match_run_item(env):
    run_id = "run_retry_1"
    await mr.write_manifest(
        run_id,
        {
            "id": run_id,
            "status": "failed",
            "mode": "claude-ensemble",
            "job_count": 1,
            "parsed_count": 0,
            "matched_count": 0,
            "created_at": "x",
            "updated_at": "x",
            "error": "boom",
        },
    )
    line = json.dumps(
        {"provider": "gh", "source_key": "acme", "job_id": "1", "title": "T", "company": "acme"}
    )
    mr.match_run_input_path(run_id).parent.mkdir(parents=True, exist_ok=True)
    mr.match_run_input_path(run_id).write_text(line + "\n")

    await queue_store.upsert_queue_item(
        {
            "id": f"{run_id}:gh|acme|1",
            "job_key": "gh|acme|1",
            "title": "T",
            "company": "acme",
            "mode": "claude-ensemble",
            "status": "retrying",
            "next_retry_at": "2020-01-01T00:00:00Z",
            "subtasks": [
                {"id": "parse", "status": "done"},
                {"id": "score"},
                {"id": "discord"},
            ],
            "attempt": 1,
            "max_attempts": 3,
            "created_at": "x",
            "updated_at": "x",
            "error": "boom",
        }
    )

    await retry_scheduler._tick()

    manifest = await mr.read_manifest(run_id)
    assert manifest["status"] == "completed"
    item = (await queue_store.read_queue())[0]
    assert item["status"] == "done"


async def test_tick_skips_match_run_item_with_no_input_file(env):
    run_id = "run_no_input"
    await mr.write_manifest(run_id, {"id": run_id, "status": "failed"})
    await queue_store.upsert_queue_item(
        {
            "id": f"{run_id}:gh|acme|1",
            "status": "retrying",
            "next_retry_at": "2020-01-01T00:00:00Z",
            "subtasks": [{"id": "model:claude"}, {"id": "discord"}],
            "mode": "claude",
            "attempt": 1,
            "max_attempts": 3,
        }
    )
    await retry_scheduler._tick()  # should not raise, just log and skip


async def test_discord_only_success_removes_item(env, monkeypatch):
    row = {
        "provider": "gh",
        "source_key": "acme",
        "job_id": "9",
        "title": "T",
        "company": "acme",
        "job_url": "https://x/9",
        "analysis": {"score_5": 4.6},
        "_run_id": "orig",
    }
    await queue_store.upsert_queue_item(
        {
            "id": "discord_orig_gh_acme_9",
            "job_key": "gh|acme|9",
            "title": "T",
            "company": "acme",
            "mode": "discord-only",
            "status": "retrying",
            "next_retry_at": "2020-01-01T00:00:00Z",
            "subtasks": [{"id": "discord", "status": "error", "error": "boom"}],
            "attempt": 1,
            "max_attempts": 3,
            "created_at": "x",
            "updated_at": "x",
            "error": json.dumps(row),
        }
    )

    async def ok_post(self, url, json=None, **kw):
        return FakeResponse(204)

    monkeypatch.setattr(config, "DISCORD_WEBHOOK_URL", "https://discord.example/webhook")
    monkeypatch.setattr("httpx.AsyncClient.post", ok_post)

    await retry_scheduler._tick()
    assert await queue_store.read_queue() == []


async def test_discord_only_failure_backs_off_original_item(env, monkeypatch):
    row = {
        "provider": "gh",
        "source_key": "acme",
        "job_id": "10",
        "title": "T",
        "company": "acme",
        "job_url": "https://x/10",
        "analysis": {"score_5": 4.6},
        "_run_id": "orig",
    }
    item_id = "discord_orig_gh_acme_10"
    await queue_store.upsert_queue_item(
        {
            "id": item_id,
            "job_key": "gh|acme|10",
            "title": "T",
            "company": "acme",
            "mode": "discord-only",
            "status": "retrying",
            "next_retry_at": "2020-01-01T00:00:00Z",
            "subtasks": [{"id": "discord", "status": "error", "error": "boom"}],
            "attempt": 1,
            "max_attempts": 3,
            "created_at": "x",
            "updated_at": "x",
            "error": json.dumps(row),
        }
    )

    async def fail_post(self, url, json=None, **kw):
        return FakeResponse(500)

    monkeypatch.setattr(config, "DISCORD_WEBHOOK_URL", "https://discord.example/webhook")
    monkeypatch.setattr(config, "SCORE_NOTIFY_MIN_SCORE", 4.0)
    monkeypatch.setattr("httpx.AsyncClient.post", fail_post)

    await retry_scheduler._tick()

    items = {i["id"]: i for i in await queue_store.read_queue()}
    original = items[item_id]
    assert original["status"] == "retrying"
    assert original["attempt"] == 2
    assert original["subtasks"][0]["status"] == "error"


async def test_discord_only_missing_error_field_is_noop(env):
    await queue_store.upsert_queue_item(
        {
            "id": "x",
            "status": "retrying",
            "next_retry_at": "2020-01-01T00:00:00Z",
            "subtasks": [{"id": "discord"}],
            "attempt": 1,
            "max_attempts": 3,
            "error": None,
        }
    )
    await retry_scheduler._tick()  # must not raise


async def test_start_and_stop_scheduler_task():
    task = retry_scheduler.start()
    assert not task.done()
    await retry_scheduler.stop()
    assert retry_scheduler._task is None
