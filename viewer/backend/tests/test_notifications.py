import json
from pathlib import Path

import pytest

import config
from services import notifications as n
from services import queue_store


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


@pytest.fixture(autouse=True)
def _env(isolated_env, monkeypatch):
    monkeypatch.setattr(config, "DISCORD_WEBHOOK_URL", "https://discord.example/webhook/fake")
    monkeypatch.setattr(config, "SCORE_NOTIFY_MIN_SCORE", 4.0)
    return isolated_env


def _row(**overrides):
    base = {
        "provider": "greenhouse",
        "source_key": "acme",
        "job_id": "1",
        "title": "TPM",
        "company": "acme",
        "job_url": "https://example.com/job/1",
        "location": "Fort Lauderdale",
        "employment_type": "Full-time",
        "compensation": None,
        "analysis": {"score_5": 4.6, "role_summary": {"tldr": "Great fit", "domain": "fintech"}},
    }
    base.update(overrides)
    return base


async def test_notify_skips_without_webhook_url(monkeypatch):
    monkeypatch.setattr(config, "DISCORD_WEBHOOK_URL", "")
    assert await n.notify_discord_for_score(_row(), "run_1") is False


async def test_notify_skips_below_min_score():
    row = _row(analysis={"score_5": 3.9})
    assert await n.notify_discord_for_score(row, "run_1") is False


async def test_notify_skips_non_string_job_keys():
    row = _row(provider=None)
    assert await n.notify_discord_for_score(row, "run_1") is False


async def test_notify_sends_and_builds_embed(monkeypatch):
    captured = {}

    async def fake_post(self, url, json=None, **kw):
        captured["payload"] = json
        return FakeResponse(204)

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
    sent = await n.notify_discord_for_score(_row(), "run_1")
    assert sent is True
    embed = captured["payload"]["embeds"][0]
    assert embed["title"] == "TPM"
    assert embed["url"] == "https://example.com/job/1"
    assert embed["description"] == "Great fit"
    assert embed["color"] == 3066993
    assert "author" not in embed
    assert any(f["name"] == "Score" and f["value"] == "4.6/5" for f in embed["fields"])
    assert any(f["name"] == "Domain" and f["value"] == "fintech" for f in embed["fields"])
    assert captured["payload"]["allowed_mentions"] == {"parse": []}
    assert captured["payload"]["username"] == "Job Scanner"


async def test_notify_omits_invalid_url(monkeypatch):
    captured = {}

    async def fake_post(self, url, json=None, **kw):
        captured["payload"] = json
        return FakeResponse(204)

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
    row = _row(job_url="javascript:alert(1)")
    await n.notify_discord_for_score(row, "run_1")
    assert "url" not in captured["payload"]["embeds"][0]


async def test_notify_dedups_same_or_lower_score(monkeypatch):
    async def fake_post(self, url, json=None, **kw):
        return FakeResponse(204)

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
    await n.notify_discord_for_score(_row(), "run_1")
    sent_again = await n.notify_discord_for_score(_row(), "run_2")
    assert sent_again is False


async def test_notify_resends_on_higher_score(monkeypatch):
    async def fake_post(self, url, json=None, **kw):
        return FakeResponse(204)

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
    await n.notify_discord_for_score(_row(), "run_1")
    higher = _row(analysis={"score_5": 4.9})
    assert await n.notify_discord_for_score(higher, "run_2") is True


async def test_notify_failure_enqueues_discord_only_item_and_raises(monkeypatch):
    async def fail_post(self, url, json=None, **kw):
        return FakeResponse(500)

    monkeypatch.setattr("httpx.AsyncClient.post", fail_post)
    with pytest.raises(RuntimeError, match="Discord webhook failed"):
        await n.notify_discord_for_score(_row(), "run_9")

    items = await queue_store.read_queue()
    assert len(items) == 1
    item = items[0]
    assert item["mode"] == "discord-only"
    assert item["status"] == "retrying"
    assert len(item["subtasks"]) == 1 and item["subtasks"][0]["id"] == "discord"
    payload_row = json.loads(item["error"])
    assert payload_row["_run_id"] == "run_9"


async def test_read_hidden_jobs_missing_file_returns_empty_set():
    assert await n.read_hidden_jobs() == set()


async def test_write_and_read_hidden_jobs_round_trip():
    await n.write_hidden_jobs({"b|b|2", "a|a|1"})
    result = await n.read_hidden_jobs()
    assert result == {"a|a|1", "b|b|2"}


async def test_write_hidden_jobs_persists_sorted_with_timestamp():
    await n.write_hidden_jobs({"b|b|2", "a|a|1"})
    raw = json.loads(Path(config.HIDDEN_JOBS_PATH).read_text())
    assert raw["hidden"] == ["a|a|1", "b|b|2"]
    assert "updated_at" in raw


async def test_read_score_notifications_missing_file():
    assert await n.read_score_notifications() == {"sent": {}}
