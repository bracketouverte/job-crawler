def test_get_auto_analyzer_default_state(app_client):
    r = app_client.get("/api/auto-analyzer")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["paused"] is False
    assert body["busy"] is False
    assert body["current"] is None


def test_post_auto_analyzer_pauses_and_unpauses(app_client):
    r = app_client.post("/api/auto-analyzer", json={"paused": True})
    assert r.status_code == 200
    assert r.json()["paused"] is True

    r = app_client.get("/api/auto-analyzer")
    assert r.json()["paused"] is True

    r = app_client.post("/api/auto-analyzer", json={"paused": False})
    assert r.json()["paused"] is False
