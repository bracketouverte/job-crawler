import config


def test_get_config_short_model_names(app_client, monkeypatch):
    monkeypatch.setattr(config, "NVIDIA_ENSEMBLE_SCORERS", "org/model-a,org2/model-b")
    monkeypatch.setattr(config, "NVIDIA_ENSEMBLE_SYNTHESIZER", "org3/model-c")
    r = app_client.get("/api/config")
    body = r.json()
    assert body["ensembleScorers"] == ["model-a", "model-b"]
    assert body["ensembleSynthesizer"] == "model-c"
    assert body["savedSearchAnalyzerEnabled"] is True


def test_crawl_status_missing_progress_file_defaults_active(app_client):
    r = app_client.get("/api/crawl-status")
    body = r.json()
    assert body["active"] is True
    assert body["progress"] is None
    assert "next_run" in body


def test_crawl_status_reads_progress_and_lock(app_client, migrated_env):
    import json
    from pathlib import Path

    Path(config.CRAWLER_PROGRESS_PATH).write_text(json.dumps({"scanned": 10}))
    Path(config.CRAWLER_ACTIVE_LOCK_PATH).write_text("")

    r = app_client.get("/api/crawl-status")
    body = r.json()
    assert body["active"] is True
    assert body["progress"] == {"scanned": 10}


def test_hidden_jobs_get_and_put(app_client):
    r = app_client.get("/api/hidden-jobs")
    assert r.json() == {"hidden": []}

    r = app_client.put("/api/hidden-jobs", json={"hidden": ["b|b|2", "a|a|1", "  "]})
    assert r.status_code == 200
    assert r.json() == {"hidden": ["a|a|1", "b|b|2"]}

    r = app_client.get("/api/hidden-jobs")
    assert r.json() == {"hidden": ["a|a|1", "b|b|2"]}


def test_logo_dev_brand_no_secret_key_returns_null_domain(app_client, monkeypatch):
    monkeypatch.setattr(config, "LOGO_DEV_SECRET_KEY", None)
    r = app_client.get("/api/logo-dev/brand?company=Acme")
    assert r.status_code == 200
    assert r.json() == {"domain": None}


def test_logo_dev_brand_requires_company(app_client, monkeypatch):
    monkeypatch.setattr(config, "LOGO_DEV_SECRET_KEY", "secret")
    r = app_client.get("/api/logo-dev/brand")
    assert r.status_code == 400


def test_logo_dev_brand_uses_cache(app_client, monkeypatch):
    monkeypatch.setattr(config, "LOGO_DEV_SECRET_KEY", "secret")
    from services.company import logo_dev_brand_cache

    logo_dev_brand_cache["acme"] = "acme.com"
    r = app_client.get("/api/logo-dev/brand?company=Acme")
    assert r.status_code == 200
    assert r.json() == {"domain": "acme.com"}
    logo_dev_brand_cache.clear()


def test_logo_dev_brand_success(app_client, monkeypatch):
    monkeypatch.setattr(config, "LOGO_DEV_SECRET_KEY", "secret")

    class FakeResponse:
        status_code = 200

        def json(self):
            return [{"domain": "acme.com"}]

    async def fake_get(self, url, params=None, headers=None, **kw):
        assert params == {"q": "Acme", "strategy": "match"}
        assert headers == {"Authorization": "Bearer secret"}
        return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)
    r = app_client.get("/api/logo-dev/brand?company=Acme")
    assert r.status_code == 200
    assert r.json() == {"domain": "acme.com"}

    from services.company import logo_dev_brand_cache

    assert logo_dev_brand_cache["acme"] == "acme.com"
    logo_dev_brand_cache.clear()


def test_logo_dev_brand_upstream_failure_returns_502(app_client, monkeypatch):
    monkeypatch.setattr(config, "LOGO_DEV_SECRET_KEY", "secret")

    class FailResponse:
        status_code = 401

        def json(self):
            return {}

    async def fake_get(self, url, params=None, headers=None, **kw):
        return FailResponse()

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)
    r = app_client.get("/api/logo-dev/brand?company=Acme")
    assert r.status_code == 502
