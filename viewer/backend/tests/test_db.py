import pytest

from db import execute, executemany, fetchall, fetchone, run_migrations
from tests.conftest import insert_job


@pytest.fixture(autouse=True)
def _env(isolated_env):
    return isolated_env


async def test_fetchall_and_fetchone(isolated_env):
    insert_job(isolated_env["catalog_db"], job_id="1", title="A")
    insert_job(isolated_env["catalog_db"], job_id="2", title="B")

    rows = await fetchall("SELECT title FROM catalog_jobs ORDER BY title")
    assert [r["title"] for r in rows] == ["A", "B"]

    row = await fetchone("SELECT title FROM catalog_jobs WHERE job_id = ?", ("1",))
    assert row["title"] == "A"

    missing = await fetchone("SELECT title FROM catalog_jobs WHERE job_id = ?", ("nope",))
    assert missing is None


async def test_execute_and_executemany(isolated_env):
    await execute(
        "INSERT INTO catalog_jobs (provider, source_key, job_id, title) VALUES (?, ?, ?, ?)",
        ("gh", "acme", "1", "Solo"),
    )
    await executemany(
        "INSERT INTO catalog_jobs (provider, source_key, job_id, title) VALUES (?, ?, ?, ?)",
        [("gh", "acme", "2", "Batch1"), ("gh", "acme", "3", "Batch2")],
    )
    rows = await fetchall("SELECT title FROM catalog_jobs ORDER BY job_id")
    assert [r["title"] for r in rows] == ["Solo", "Batch1", "Batch2"]


async def test_run_migrations_adds_columns_and_tables(isolated_env):
    await run_migrations()
    # analysis_score / parsed_jd columns should now exist without error
    await execute("UPDATE catalog_jobs SET analysis_score = 4.0, parsed_jd = '{}' WHERE 1=0")
    tables = await fetchall("SELECT name FROM sqlite_master WHERE type = 'table'")
    names = {t["name"] for t in tables}
    assert "job_analyses" in names
    assert "catalog_jobs_fts" not in names  # title search uses LIKE; no FTS index is built


async def test_run_migrations_is_idempotent(isolated_env):
    await run_migrations()
    await run_migrations()  # must not raise on the second pass (duplicate column etc.)
    rows = await fetchall("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'job_analyses'")
    assert len(rows) == 1


async def test_run_migrations_against_real_crawler_schema(isolated_env):
    """The crawler's actual catalog_jobs schema has a composite primary key
    (provider, source_key, job_id) and no explicit "id" column — unlike this
    test suite's own fixture schema. Migrations must work against that real
    shape too, and must leave the catalog rows intact."""
    import sqlite3

    conn = sqlite3.connect(isolated_env["catalog_db"])
    conn.executescript(
        "DROP TABLE catalog_jobs;"
        "CREATE TABLE catalog_jobs ("
        "  provider TEXT NOT NULL, source_key TEXT NOT NULL, job_id TEXT NOT NULL,"
        "  title TEXT, location TEXT, employment_type TEXT, compensation TEXT,"
        "  department TEXT, office TEXT, language TEXT, updated_at TEXT, posted_at TEXT,"
        "  job_url TEXT, fetched_at TEXT NOT NULL, first_seen_at TEXT NOT NULL,"
        "  last_seen_at TEXT NOT NULL, seen_run_id TEXT NOT NULL,"
        "  raw_json TEXT NOT NULL DEFAULT 'null',"
        "  PRIMARY KEY (provider, source_key, job_id)"
        ");"
    )
    conn.execute(
        "INSERT INTO catalog_jobs (provider, source_key, job_id, title, fetched_at, "
        "first_seen_at, last_seen_at, seen_run_id) "
        "VALUES ('gh', 'acme', '1', 'Backend Engineer', 'x', 'x', 'x', 'run1')"
    )
    conn.commit()
    conn.close()

    await run_migrations()  # must not raise sqlite3.OperationalError: no such column: T.id

    row = await fetchone("SELECT COUNT(*) AS n FROM catalog_jobs")
    assert row["n"] == 1
