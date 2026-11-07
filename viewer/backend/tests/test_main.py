import importlib

import pytest

import config


@pytest.fixture
def static_app_client(isolated_env, monkeypatch):
    """main.py decides whether to mount the SPA (and registers the 404
    fallback handler) once, at import time, based on config.STATIC_DIR.
    Every other test in the suite relies on main already being imported
    with the default (non-existent) STATIC_DIR, so this reloads main with
    a real static dir just for this test and reloads it back afterward to
    avoid leaking the SPA-mounted app into later tests."""
    static_dir = isolated_env["tmp_path"] / "static"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text("<html><body>SPA ROOT</body></html>")
    (static_dir / "assets" / "style.css").write_text("body { color: red; }")

    monkeypatch.setattr(config, "STATIC_DIR", str(static_dir))

    import main

    importlib.reload(main)

    from fastapi.testclient import TestClient

    with TestClient(main.app) as client:
        yield client

    monkeypatch.undo()
    importlib.reload(main)


def test_root_serves_index_html(static_app_client):
    r = static_app_client.get("/")
    assert r.status_code == 200
    assert "SPA ROOT" in r.text


def test_static_asset_served_with_content_type(static_app_client):
    r = static_app_client.get("/assets/style.css")
    assert r.status_code == 200
    assert "color: red" in r.text
    assert "css" in r.headers["content-type"]


def test_unknown_client_route_falls_back_to_index(static_app_client):
    r = static_app_client.get("/some/client/route")
    assert r.status_code == 200
    assert "SPA ROOT" in r.text


def test_api_route_returns_json_not_html(static_app_client):
    r = static_app_client.get("/api/jobs")
    assert r.status_code == 200
    assert "application/json" in r.headers["content-type"]


def test_api_404_is_not_swallowed_by_spa_fallback(static_app_client):
    r = static_app_client.get("/api/match-runs/does-not-exist")
    assert r.status_code == 404
    assert r.json() == {"detail": "Run not found"}


def test_root_returns_status_ok_without_static_dir(app_client):
    r = app_client.get("/")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
