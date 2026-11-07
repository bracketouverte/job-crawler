import asyncio
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_queue_store_lock():
    """services.queue_store's module-level asyncio.Lock binds lazily to
    whichever event loop first acquires it. pytest-asyncio hands each test
    function its own loop, so a lock left bound to a prior test's (now
    closed) loop would crash the next test with "bound to a different
    event loop". Giving every test a fresh, unbound Lock sidesteps that."""
    from services import queue_store

    queue_store._LOCK = asyncio.Lock()


CATALOG_SCHEMA = """
CREATE TABLE catalog_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT, source_key TEXT, job_id TEXT, title TEXT, location TEXT,
  employment_type TEXT, compensation TEXT, department TEXT, job_url TEXT,
  updated_at TEXT, posted_at TEXT, first_seen_at TEXT, last_seen_at TEXT,
  skill_tier TEXT, employment_type_canonical TEXT, lat REAL, lon REAL,
  analysis_score REAL, parsed_jd TEXT, is_remote INTEGER DEFAULT 0
)
"""


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Points every path-shaped config value at a fresh tmp_path tree and
    resets the module-level mutable singletons that live outside config
    (logo cache, active-run tracking, saved-search state)."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "match-runs").mkdir()
    frontend_public = tmp_path / "frontend" / "public"
    frontend_public.mkdir(parents=True)
    catalog_db = state_dir / "catalog.sqlite"

    conn = sqlite3.connect(str(catalog_db))
    conn.execute(CATALOG_SCHEMA)
    conn.commit()
    conn.close()

    monkeypatch.setattr(config, "CATALOG_DB", str(catalog_db))
    monkeypatch.setattr(config, "STATE_DIR", str(state_dir))
    monkeypatch.setattr(config, "MATCH_RUNS_DIR", str(state_dir / "match-runs"))
    monkeypatch.setattr(config, "ANALYSIS_CACHE_PATH", str(state_dir / "job-analysis-cache.json"))
    monkeypatch.setattr(config, "HIDDEN_JOBS_PATH", str(state_dir / "hidden-jobs.json"))
    monkeypatch.setattr(config, "SCORE_NOTIFICATIONS_PATH", str(state_dir / "score-notifications.json"))
    monkeypatch.setattr(config, "CRAWLER_ACTIVE_LOCK_PATH", str(state_dir / "crawler-active.lock"))
    monkeypatch.setattr(config, "CRAWLER_ACTIVE_LOCK_STALE_MS", 7_200_000)
    monkeypatch.setattr(config, "CRAWLER_PROGRESS_PATH", str(state_dir / "crawler-progress.json"))
    monkeypatch.setattr(config, "SAVED_SEARCHES_PATH", str(frontend_public / "saved-searches.json"))
    monkeypatch.setattr(config, "MATCHER_SERVICE_URL", "http://matcher-test-stub:8001")
    monkeypatch.setattr(config, "SAVED_SEARCH_ANALYZER_ENABLED", True)
    monkeypatch.setattr(config, "SAVED_SEARCH_ANALYZER_INTERVAL_MS", 60_000)
    monkeypatch.setattr(config, "DISCORD_WEBHOOK_URL", "")
    monkeypatch.setattr(config, "SCORE_NOTIFY_MIN_SCORE", 4.0)
    monkeypatch.setattr(config, "LOGO_DEV_PUBLISHABLE_KEY", None)
    monkeypatch.setattr(config, "LOGO_DEV_SECRET_KEY", None)
    monkeypatch.setattr(config, "USER_LOCATION", None)
    monkeypatch.setattr(config, "NVIDIA_MODEL", "meta/llama-4-maverick-17b-128e-instruct")
    monkeypatch.setattr(config, "NVIDIA_ENSEMBLE_SCORERS", None)
    monkeypatch.setattr(config, "NVIDIA_ENSEMBLE_SYNTHESIZER", None)

    from services.company import logo_dev_brand_cache

    logo_dev_brand_cache.clear()

    from services.match_run import active_run_ids

    active_run_ids.clear()

    import services.saved_search as saved_search

    saved_search.saved_search_analyzer_paused = False
    saved_search.saved_search_analyzer_busy = False
    saved_search.saved_search_analyzer_current = None

    import services.analysis as analysis_module

    analysis_module.invalidate_analysis_cache()
    analysis_module._migrated = False

    return {
        "tmp_path": tmp_path,
        "state_dir": state_dir,
        "catalog_db": catalog_db,
    }


@pytest.fixture
async def migrated_env(isolated_env):
    from db import run_migrations

    await run_migrations()
    return isolated_env


@pytest.fixture
def app_client(migrated_env):
    from fastapi.testclient import TestClient

    import main

    with TestClient(main.app) as client:
        yield client


def insert_job(catalog_db: Path, **fields) -> int:
    defaults = {
        "provider": "greenhouse",
        "source_key": "acme",
        "job_id": "1",
        "title": "Backend Engineer",
        "location": "Remote",
        "job_url": "https://example.com/job/1",
        "first_seen_at": "2026-01-01T00:00:00Z",
        "is_remote": 0,
    }
    defaults.update(fields)
    columns = ", ".join(defaults.keys())
    placeholders = ", ".join("?" for _ in defaults)
    conn = sqlite3.connect(str(catalog_db))
    cur = conn.execute(
        f"INSERT INTO catalog_jobs ({columns}) VALUES ({placeholders})",
        list(defaults.values()),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id
