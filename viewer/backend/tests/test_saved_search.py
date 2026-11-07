import json

import pytest

import config
from services import match_run as mr
from services import matcher_client, queue_store, saved_search
from tests.conftest import insert_job


@pytest.fixture
def env(isolated_env, monkeypatch):
    async def fake_parse_batch(urls):
        return [{"url": url, "parsed": {"title": "Parsed"}, "parse_error": None} for url in urls]

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

    monkeypatch.setattr(matcher_client, "parse_batch", fake_parse_batch)
    monkeypatch.setattr(matcher_client, "analyze", fake_analyze)
    return isolated_env


async def test_read_saved_searches_missing_file_returns_empty(env):
    assert await saved_search.read_saved_searches() == []


async def test_read_saved_searches_reads_valid_entries(env):
    from pathlib import Path

    Path(config.SAVED_SEARCHES_PATH).write_text(json.dumps([{"id": "s1", "label": "Search 1"}]))
    result = await saved_search.read_saved_searches()
    assert result == [{"id": "s1", "label": "Search 1"}]


async def test_is_crawler_active_false_without_lock_file(env):
    assert await saved_search.is_crawler_active() is False


async def test_is_crawler_active_true_for_fresh_lock(env):
    from pathlib import Path

    Path(config.CRAWLER_ACTIVE_LOCK_PATH).write_text("")
    assert await saved_search.is_crawler_active() is True


async def test_is_crawler_active_false_for_stale_lock(env, monkeypatch):
    import os
    import time
    from pathlib import Path

    lock_path = Path(config.CRAWLER_ACTIVE_LOCK_PATH)
    lock_path.write_text("")
    stale_time = time.time() - 3 * 60 * 60  # 3 hours ago, default stale window is 2h
    os.utime(lock_path, (stale_time, stale_time))
    assert await saved_search.is_crawler_active() is False


async def test_find_next_saved_search_job_skips_no_url_and_matches(env, migrated_env):
    from pathlib import Path

    Path(config.SAVED_SEARCHES_PATH).write_text(
        json.dumps([{"id": "s1", "label": "S1", "location": "Fort Lauderdale", "sources": "greenhouse"}])
    )
    insert_job(
        migrated_env["catalog_db"],
        job_id="1",
        location="Fort Lauderdale",
        job_url="https://x/1",
        first_seen_at="2099-01-01T00:00:00Z",
    )
    insert_job(
        migrated_env["catalog_db"],
        job_id="2",
        location="Fort Lauderdale",
        job_url=None,
        first_seen_at="2099-01-01T00:00:00Z",
    )

    result = await saved_search.find_next_saved_search_job()
    assert result is not None
    assert result["job"]["job_id"] == "1"


async def test_find_next_saved_search_job_skips_hidden(env, migrated_env):
    from pathlib import Path

    from services.notifications import write_hidden_jobs

    Path(config.SAVED_SEARCHES_PATH).write_text(json.dumps([{"id": "s1", "label": "S1"}]))
    insert_job(
        migrated_env["catalog_db"], job_id="1", job_url="https://x/1", first_seen_at="2099-01-01T00:00:00Z"
    )
    await write_hidden_jobs({"greenhouse|acme|1"})

    result = await saved_search.find_next_saved_search_job()
    assert result is None


async def test_find_next_saved_search_job_skips_queued(env, migrated_env):
    from pathlib import Path

    Path(config.SAVED_SEARCHES_PATH).write_text(json.dumps([{"id": "s1", "label": "S1"}]))
    insert_job(
        migrated_env["catalog_db"], job_id="1", job_url="https://x/1", first_seen_at="2099-01-01T00:00:00Z"
    )
    await queue_store.upsert_queue_item({"id": "run:x", "job_key": "greenhouse|acme|1", "status": "running"})

    result = await saved_search.find_next_saved_search_job()
    assert result is None


async def test_find_next_saved_search_job_no_searches_returns_none(env):
    assert await saved_search.find_next_saved_search_job() is None


async def test_run_once_skips_when_disabled(env, monkeypatch):
    monkeypatch.setattr(config, "SAVED_SEARCH_ANALYZER_ENABLED", False)
    await saved_search.run_saved_search_analyzer_once()
    assert saved_search.saved_search_analyzer_busy is False


async def test_run_once_skips_when_paused(env):
    saved_search.saved_search_analyzer_paused = True
    await saved_search.run_saved_search_analyzer_once()
    assert saved_search.saved_search_analyzer_busy is False
    saved_search.saved_search_analyzer_paused = False


async def test_run_once_skips_when_active_runs_exist(env):
    mr.active_run_ids.add("some-run")
    await saved_search.run_saved_search_analyzer_once()
    assert saved_search.saved_search_analyzer_current is None
    mr.active_run_ids.discard("some-run")


async def test_run_once_skips_when_crawler_active(env):
    from pathlib import Path

    Path(config.CRAWLER_ACTIVE_LOCK_PATH).write_text("")
    await saved_search.run_saved_search_analyzer_once()
    assert saved_search.saved_search_analyzer_busy is False


async def test_run_once_no_eligible_job_is_noop(env, migrated_env):
    await saved_search.run_saved_search_analyzer_once()
    assert saved_search.saved_search_analyzer_busy is False
    assert saved_search.saved_search_analyzer_current is None


async def test_run_once_scores_next_job_via_ensemble(env, migrated_env):
    from pathlib import Path

    Path(config.SAVED_SEARCHES_PATH).write_text(json.dumps([{"id": "s1", "label": "S1"}]))
    insert_job(
        migrated_env["catalog_db"], job_id="1", job_url="https://x/1", first_seen_at="2099-01-01T00:00:00Z"
    )

    await saved_search.run_saved_search_analyzer_once()

    assert saved_search.saved_search_analyzer_busy is False
    assert saved_search.saved_search_analyzer_current is None

    from services.analysis import get_analysis_cache

    cache = await get_analysis_cache()
    assert "greenhouse|acme|1" in cache
