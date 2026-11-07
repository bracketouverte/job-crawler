import json

import pytest

from db import fetchall
from services.analysis import (
    analysis_score_5,
    best_analysis,
    get_analysis_cache,
    has_full_analysis,
    invalidate_analysis_cache,
    parse_job_key,
    persist_run_results,
    upsert_analysis,
)


@pytest.fixture(autouse=True)
def _env(isolated_env):
    return isolated_env


def test_parse_job_key_splits_provider_source_job():
    assert parse_job_key("greenhouse|acme|123") == ("greenhouse", "acme", "123")


def test_parse_job_key_rejoins_extra_pipes_into_job_id():
    assert parse_job_key("workday|acme/careers|job/123") == ("workday", "acme/careers", "job/123")


def test_parse_job_key_too_few_parts_returns_none():
    assert parse_job_key("only|two") is None


def test_analysis_score_5_valid():
    assert analysis_score_5({"score_5": 4.5}) == 4.5


def test_analysis_score_5_missing_or_invalid():
    assert analysis_score_5({}) is None
    assert analysis_score_5(None) is None
    assert analysis_score_5({"score_5": "not-a-number"}) is None
    assert analysis_score_5({"score_5": float("nan")}) is None


def test_best_analysis_prefers_ensemble_over_maverick():
    entry = {
        "pipelines": {
            "claude": {"analysis": {"tag": "quick"}},
            "claude-ensemble": {"analysis": {"tag": "full"}},
        }
    }
    assert best_analysis(entry)["tag"] == "full"


def test_best_analysis_falls_back_to_maverick():
    entry = {"pipelines": {"claude": {"analysis": {"tag": "quick"}}}}
    assert best_analysis(entry)["tag"] == "quick"


def test_best_analysis_falls_back_to_latest_by_analyzed_at():
    entry = {
        "pipelines": {
            "legacy1": {"analysis": {"tag": "old"}, "analyzed_at": "2026-01-01T00:00:00Z"},
            "legacy2": {"analysis": {"tag": "new"}, "analyzed_at": "2026-06-01T00:00:00Z"},
        }
    }
    assert best_analysis(entry)["tag"] == "new"


def test_best_analysis_none_when_empty():
    assert best_analysis(None) is None
    assert best_analysis({}) is None


def test_has_full_analysis_true_only_for_ensemble():
    assert has_full_analysis({"pipelines": {"claude-ensemble": {}}}) is True
    assert has_full_analysis({"pipelines": {"claude": {}}}) is False
    assert has_full_analysis(None) is False


async def test_upsert_analysis_and_cache_round_trip(migrated_env):
    await upsert_analysis("gh|acme|1", "claude", {"score_5": 4.2}, "run_1")
    cache = await get_analysis_cache()
    entry = cache["gh|acme|1"]
    assert entry["pipelines"]["claude"]["analysis"] == {"score_5": 4.2}
    assert entry["pipelines"]["claude"]["run_id"] == "run_1"


async def test_upsert_analysis_writes_score_to_catalog_jobs(migrated_env):
    from tests.conftest import insert_job

    insert_job(migrated_env["catalog_db"], provider="gh", source_key="acme", job_id="1")
    await upsert_analysis("gh|acme|1", "claude", {"score_5": 4.7}, "run_1")
    rows = await fetchall("SELECT analysis_score FROM catalog_jobs WHERE job_id = '1'")
    assert rows[0]["analysis_score"] == 4.7


async def test_upsert_analysis_invalidates_cache(migrated_env):
    await get_analysis_cache()
    await upsert_analysis("gh|acme|2", "claude", {"score_5": 3.0}, "run_2")
    cache = await get_analysis_cache()
    assert "gh|acme|2" in cache


async def test_get_analysis_cache_ttl_reuses_within_window(migrated_env, monkeypatch):
    # Prime the one-time legacy-cache-migration check first so it isn't
    # counted below as one of the "reuse within TTL" cache-population calls.
    await get_analysis_cache()

    calls = []
    original_fetchall = fetchall

    async def counting_fetchall(sql, params=()):
        calls.append(sql)
        return await original_fetchall(sql, params)

    import services.analysis as analysis_module

    monkeypatch.setattr(analysis_module, "fetchall", counting_fetchall)
    await get_analysis_cache()
    await get_analysis_cache()
    job_analyses_calls = [c for c in calls if "job_analyses" in c]
    assert len(job_analyses_calls) == 0  # second call reused the still-warm 5s cache


async def test_persist_run_results_upserts_ok_rows_only(migrated_env):
    results = [
        {
            "status": "ok",
            "provider": "gh",
            "source_key": "acme",
            "job_id": "1",
            "analysis": {"score_5": 4.1, "pipeline": "maverick"},
        },
        {"status": "error", "provider": "gh", "source_key": "acme", "job_id": "2", "error": "boom"},
    ]
    await persist_run_results(results, "run_x")
    cache = await get_analysis_cache()
    assert "gh|acme|1" in cache
    assert "gh|acme|2" not in cache


async def test_persist_run_results_calls_notify_fn_for_ok_rows(migrated_env):
    notified = []

    async def fake_notify(row, run_id):
        notified.append((row["job_id"], run_id))

    results = [
        {
            "status": "ok",
            "provider": "gh",
            "source_key": "acme",
            "job_id": "1",
            "analysis": {"score_5": 4.1, "pipeline": "maverick"},
        },
    ]
    await persist_run_results(results, "run_y", fake_notify)
    assert notified == [("1", "run_y")]


async def test_persist_run_results_no_notify_fn_does_not_raise(migrated_env):
    results = [
        {
            "status": "ok",
            "provider": "gh",
            "source_key": "acme",
            "job_id": "1",
            "analysis": {"score_5": 4.1, "pipeline": "maverick"},
        },
    ]
    await persist_run_results(results, "run_z")  # no notify_fn


async def test_migrate_legacy_cache_if_empty(migrated_env):
    import aiofiles

    import config

    legacy = {
        "gh|acme|1": {
            "pipelines": {
                "claude": {
                    "analysis": {"score_5": 4.0},
                    "analyzed_at": "2026-01-01T00:00:00Z",
                    "run_id": "r1",
                }
            }
        }
    }
    async with aiofiles.open(config.ANALYSIS_CACHE_PATH, "w") as f:
        await f.write(json.dumps(legacy))

    invalidate_analysis_cache()
    cache = await get_analysis_cache()
    assert "gh|acme|1" in cache
    assert cache["gh|acme|1"]["pipelines"]["claude"]["analysis"] == {"score_5": 4.0}
