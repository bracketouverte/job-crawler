from catalog_store import CatalogStore
from models import NormalizedJob


def _job(**overrides) -> NormalizedJob:
    defaults = dict(
        provider="greenhouse",
        source_key="acme",
        job_id="1",
        fetched_at="2026-01-01T00:00:00Z",
        title="Senior Backend Engineer",
        location="Miami, FL",
    )
    defaults.update(overrides)
    return NormalizedJob(**defaults)


def test_upsert_inserts_new_row(tmp_path):
    store = CatalogStore(str(tmp_path / "catalog.sqlite"))
    store.record_jobs([_job()], "run1")

    row = store.db.execute("SELECT * FROM catalog_jobs").fetchone()
    assert row is not None
    store.close()


def test_upsert_same_key_updates_in_place_not_duplicated(tmp_path):
    store = CatalogStore(str(tmp_path / "catalog.sqlite"))
    store.record_jobs([_job(title="Old Title")], "run1")
    store.record_jobs([_job(title="New Title")], "run2")

    rows = store.db.execute("SELECT title FROM catalog_jobs").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "New Title"
    store.close()


def test_first_seen_at_set_once_not_updated(tmp_path):
    store = CatalogStore(str(tmp_path / "catalog.sqlite"))
    store.record_jobs([_job(posted_at="2025-06-01T00:00:00Z")], "run1")
    first = store.db.execute("SELECT first_seen_at FROM catalog_jobs").fetchone()[0]

    store.record_jobs([_job(posted_at="2026-01-01T00:00:00Z")], "run2")
    second = store.db.execute("SELECT first_seen_at FROM catalog_jobs").fetchone()[0]

    assert first == second == "2025-06-01T00:00:00Z"
    store.close()


def test_first_seen_at_falls_back_to_fetched_at_without_posted_at(tmp_path):
    store = CatalogStore(str(tmp_path / "catalog.sqlite"))
    store.record_jobs([_job(posted_at=None, fetched_at="2026-01-01T00:00:00Z")], "run1")
    row = store.db.execute("SELECT first_seen_at, last_seen_at FROM catalog_jobs").fetchone()
    assert row[0] == "2026-01-01T00:00:00Z"
    assert row[1] == "2026-01-01T00:00:00Z"
    store.close()


def test_raw_json_is_always_literal_null_string(tmp_path):
    store = CatalogStore(str(tmp_path / "catalog.sqlite"))
    store.record_jobs([_job()], "run1")
    raw_json = store.db.execute("SELECT raw_json FROM catalog_jobs").fetchone()[0]
    assert raw_json == "null"
    store.close()


def test_skill_tier_and_employment_type_canonical_computed_on_upsert(tmp_path):
    store = CatalogStore(str(tmp_path / "catalog.sqlite"))
    store.record_jobs([_job(title="Senior Backend Engineer", employment_type="Full-time")], "run1")
    row = store.db.execute("SELECT skill_tier, employment_type_canonical FROM catalog_jobs").fetchone()
    assert row[0] == "senior"
    assert row[1] == "Full-time"
    store.close()


def test_lat_lon_populated_from_resolve_coords(tmp_path):
    store = CatalogStore(str(tmp_path / "catalog.sqlite"))
    store.record_jobs([_job(location="Miami, FL")], "run1")
    row = store.db.execute("SELECT lat, lon FROM catalog_jobs").fetchone()
    assert row[0] is not None
    assert row[1] is not None
    store.close()


def test_lat_lon_null_for_unresolvable_location(tmp_path):
    store = CatalogStore(str(tmp_path / "catalog.sqlite"))
    store.record_jobs([_job(location="Remote")], "run1")
    row = store.db.execute("SELECT lat, lon FROM catalog_jobs").fetchone()
    assert row[0] is None
    assert row[1] is None
    store.close()


def test_finalize_run_deletes_rows_from_other_runs(tmp_path):
    store = CatalogStore(str(tmp_path / "catalog.sqlite"))
    store.record_jobs([_job(job_id="1")], "run1")
    store.record_jobs([_job(job_id="2")], "run2")

    store.finalize_run("run2")

    rows = store.db.execute("SELECT job_id FROM catalog_jobs").fetchall()
    assert [r[0] for r in rows] == ["2"]
    store.close()


def test_ensure_column_is_idempotent_against_existing_columns(tmp_path):
    db_path = str(tmp_path / "catalog.sqlite")
    store1 = CatalogStore(db_path)
    store1.close()

    # Re-opening against a DB that already has the incrementally-added
    # columns must not raise "duplicate column".
    store2 = CatalogStore(db_path)
    cols = {row[1] for row in store2.db.execute("PRAGMA table_info(catalog_jobs)").fetchall()}
    assert {"posted_at", "skill_tier", "employment_type_canonical", "lat", "lon"} <= cols
    store2.close()


def test_pragmas_applied(tmp_path):
    store = CatalogStore(str(tmp_path / "catalog.sqlite"))
    journal_mode = store.db.execute("PRAGMA journal_mode").fetchone()[0]
    assert journal_mode.lower() == "wal"
    store.close()


def test_composite_primary_key_no_id_column(tmp_path):
    store = CatalogStore(str(tmp_path / "catalog.sqlite"))
    cols = [row[1] for row in store.db.execute("PRAGMA table_info(catalog_jobs)").fetchall()]
    assert "id" not in cols
    pk_cols = [row[1] for row in store.db.execute("PRAGMA table_info(catalog_jobs)").fetchall() if row[5] > 0]
    assert set(pk_cols) == {"provider", "source_key", "job_id"}
    store.close()


def test_record_jobs_wraps_in_transaction_rolls_back_on_error(tmp_path, monkeypatch):
    import catalog_store as catalog_store_module

    store = CatalogStore(str(tmp_path / "catalog.sqlite"))

    calls = {"n": 0}
    original_resolve_coords = catalog_store_module.resolve_coords

    def failing_resolve_coords(location):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return original_resolve_coords(location)

    monkeypatch.setattr(catalog_store_module, "resolve_coords", failing_resolve_coords)

    try:
        store.record_jobs([_job(job_id="1"), _job(job_id="2")], "run1")
    except RuntimeError:
        pass

    rows = store.db.execute("SELECT job_id FROM catalog_jobs").fetchall()
    assert rows == []  # the whole batch rolled back, not a partial commit
    store.close()


def test_is_remote_set_when_location_says_remote(tmp_path):
    store = CatalogStore(str(tmp_path / "catalog.sqlite"))
    store.record_jobs([_job(job_id="1", location="Remote, USA")], "run1")
    store.record_jobs([_job(job_id="2", location="Remote North America")], "run1")
    rows = store.db.execute("SELECT job_id, is_remote FROM catalog_jobs ORDER BY job_id").fetchall()
    assert rows == [("1", 1), ("2", 1)]
    store.close()


def test_is_remote_zero_for_on_site_location(tmp_path):
    store = CatalogStore(str(tmp_path / "catalog.sqlite"))
    store.record_jobs([_job(location="Taipei, Taiwan")], "run1")
    assert store.db.execute("SELECT is_remote FROM catalog_jobs").fetchone()[0] == 0
    store.close()


def test_is_remote_null_without_location(tmp_path):
    store = CatalogStore(str(tmp_path / "catalog.sqlite"))
    store.record_jobs([_job(location=None)], "run1")
    assert store.db.execute("SELECT is_remote FROM catalog_jobs").fetchone()[0] is None
    store.close()


def test_is_remote_does_not_match_inside_words(tmp_path):
    store = CatalogStore(str(tmp_path / "catalog.sqlite"))
    store.record_jobs([_job(location="Remotely hosted, Berlin")], "run1")
    assert store.db.execute("SELECT is_remote FROM catalog_jobs").fetchone()[0] == 0
    store.close()
