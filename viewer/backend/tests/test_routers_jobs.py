from tests.conftest import insert_job


def test_list_jobs_empty(app_client):
    r = app_client.get("/api/jobs")
    assert r.status_code == 200
    body = r.json()
    assert body == {"jobs": [], "total": 0, "page": 1, "limit": 50}


def test_list_jobs_remote_0_no_location_returns_empty(app_client, migrated_env):
    # Living inline documentation of Story 9.1's specific acceptance case:
    # remote excluded + no location given is an impossible filter server-side
    # (services/filters.py appends "1 = 0"), and the route must surface that
    # as a clean empty result, not an error.
    insert_job(migrated_env["catalog_db"], job_id="1", location="Miami, FL", is_remote=0)
    r = app_client.get("/api/jobs?remote=0")
    assert r.status_code == 200
    assert r.json() == {"jobs": [], "total": 0, "page": 1, "limit": 50}


def test_list_jobs_returns_sanitized_rows(app_client, migrated_env):
    insert_job(migrated_env["catalog_db"], job_id="1", title="Backend Engineer", compensation="REQ-123")
    r = app_client.get("/api/jobs")
    body = r.json()
    assert body["total"] == 1
    job = body["jobs"][0]
    assert job["title"] == "Backend Engineer"
    assert job["compensation"] is None  # junk compensation sanitized
    assert job["analysis"] is None
    assert job["pipelines"] == {}


def test_list_jobs_pagination(app_client, migrated_env):
    for i in range(3):
        insert_job(
            migrated_env["catalog_db"], job_id=str(i), title=f"Job {i}", first_seen_at="2026-01-01T00:00:00Z"
        )
    r = app_client.get("/api/jobs?limit=2&page=1")
    body = r.json()
    assert body["total"] == 3
    assert len(body["jobs"]) == 2
    assert body["limit"] == 2


def test_list_jobs_company_filter(app_client, migrated_env):
    insert_job(migrated_env["catalog_db"], job_id="1", source_key="acme", title="A")
    insert_job(migrated_env["catalog_db"], job_id="2", source_key="other", title="B")
    r = app_client.get("/api/jobs?company=acme")
    body = r.json()
    assert body["total"] == 1
    assert body["jobs"][0]["source_key"] == "acme"


def test_get_job_requires_full_key(app_client):
    r = app_client.get("/api/job")
    assert r.status_code == 400


def test_get_job_not_found(app_client):
    r = app_client.get("/api/job?provider=gh&source_key=acme&job_id=999")
    assert r.status_code == 404


def test_get_job_found(app_client, migrated_env):
    insert_job(migrated_env["catalog_db"], provider="gh", source_key="acme", job_id="1", title="X")
    r = app_client.get("/api/job?provider=gh&source_key=acme&job_id=1")
    assert r.status_code == 200
    assert r.json()["title"] == "X"


def test_get_job_parsed_requires_full_key(app_client):
    r = app_client.get("/api/job-parsed")
    assert r.status_code == 400


def test_get_job_parsed_not_yet_parsed(app_client, migrated_env):
    insert_job(migrated_env["catalog_db"], provider="gh", source_key="acme", job_id="1")
    r = app_client.get("/api/job-parsed?provider=gh&source_key=acme&job_id=1")
    assert r.status_code == 404
    assert r.json()["detail"] == "Not yet parsed — run analysis first"


def test_get_job_parsed_returns_json(app_client, migrated_env):
    import json

    insert_job(
        migrated_env["catalog_db"],
        provider="gh",
        source_key="acme",
        job_id="1",
        parsed_jd=json.dumps({"title": "Parsed"}),
    )
    r = app_client.get("/api/job-parsed?provider=gh&source_key=acme&job_id=1")
    assert r.status_code == 200
    assert r.json() == {"title": "Parsed"}


def test_list_sources(app_client, migrated_env):
    insert_job(migrated_env["catalog_db"], provider="gh", job_id="1")
    insert_job(migrated_env["catalog_db"], provider="lever", job_id="2")
    r = app_client.get("/api/sources")
    assert sorted(r.json()["sources"]) == ["gh", "lever"]


def test_get_stats(app_client, migrated_env):
    insert_job(migrated_env["catalog_db"], provider="gh", job_id="1", last_seen_at="2026-01-01T00:00:00Z")
    insert_job(migrated_env["catalog_db"], provider="gh", job_id="2", last_seen_at="2026-02-01T00:00:00Z")
    r = app_client.get("/api/stats")
    body = r.json()
    assert body["total"] == 2
    assert body["byProvider"] == [{"provider": "gh", "count": 2}]
    assert body["lastCrawl"] == "2026-02-01T00:00:00Z"


def test_get_trends_missing_file_returns_empty_list(app_client):
    r = app_client.get("/api/trends")
    assert r.status_code == 200
    assert r.json() == []


def test_get_trends_reads_last_30_lines(app_client, migrated_env):
    import json
    from pathlib import Path

    import config

    path = Path(config.STATE_DIR) / "trends.jsonl"
    path.write_text("\n".join(json.dumps({"n": i}) for i in range(35)) + "\n")
    r = app_client.get("/api/trends")
    body = r.json()
    assert len(body) == 30
    assert body[0]["n"] == 5
    assert body[-1]["n"] == 34
