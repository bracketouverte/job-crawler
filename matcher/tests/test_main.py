import dataclasses

from fastapi.testclient import TestClient

import main


def test_health_reports_profile_loaded(profile_dir, monkeypatch):
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, career_ops_dir=str(profile_dir)))
    with TestClient(main.app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "profile_loaded": True}


def test_health_reports_profile_not_loaded_on_missing_dir(tmp_path, monkeypatch):
    missing = tmp_path / "does-not-exist"
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, career_ops_dir=str(missing)))
    with TestClient(main.app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["profile_loaded"] is False
