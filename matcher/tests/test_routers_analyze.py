import asyncio
import dataclasses

import pytest
from fastapi.testclient import TestClient

import main
from routers import analyze


@pytest.fixture
def client(monkeypatch, profile_dir):
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, career_ops_dir=str(profile_dir)))
    with TestClient(main.app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_run_tracking():
    analyze.active_tasks.clear()
    analyze.run_status.clear()
    yield
    analyze.active_tasks.clear()
    analyze.run_status.clear()


def test_analyze_quick_success(client, monkeypatch):
    async def fake_score(job, profile_data, model):
        return {"score": 80, "pipeline": "maverick"}

    monkeypatch.setattr(analyze, "score_job_quick", fake_score)

    resp = client.post(
        "/analyze/quick",
        json={"jobs": [{"provider": "greenhouse", "source_key": "acme", "job_id": "1", "title": "TPM"}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["results"][0]["status"] == "ok"
    assert body["results"][0]["analysis"]["score"] == 80
    assert body["run_id"].startswith("run_")


def test_analyze_quick_partial_failure(client, monkeypatch):
    async def fake_score(job, profile_data, model):
        raise RuntimeError("LLM timeout")

    monkeypatch.setattr(analyze, "score_job_quick", fake_score)

    resp = client.post(
        "/analyze/quick", json={"jobs": [{"provider": "greenhouse", "source_key": "acme", "job_id": "1"}]}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["results"][0]["status"] == "error"
    assert "LLM timeout" in body["results"][0]["error"]


def test_analyze_quick_echoes_supplied_run_id(client, monkeypatch):
    async def fake_score(job, profile_data, model):
        return {"score": 80, "pipeline": "maverick"}

    monkeypatch.setattr(analyze, "score_job_quick", fake_score)

    resp = client.post(
        "/analyze/quick",
        json={
            "jobs": [{"provider": "greenhouse", "source_key": "acme", "job_id": "1"}],
            "run_id": "run_caller_supplied",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["run_id"] == "run_caller_supplied"
    assert "run_caller_supplied" not in analyze.active_tasks


def test_analyze_ensemble_sequential(client, monkeypatch):
    async def fake_score(job, profile_data):
        return {"score": 90, "pipeline": "ensemble"}

    monkeypatch.setattr(analyze, "score_job_ensemble", fake_score)
    monkeypatch.setattr(
        analyze, "settings", dataclasses.replace(analyze.settings, ensemble_job_concurrency=1)
    )

    resp = client.post(
        "/analyze/ensemble", json={"jobs": [{"provider": "lever", "source_key": "acme", "job_id": "1"}]}
    )
    assert resp.status_code == 200
    assert resp.json()["results"][0]["analysis"]["score"] == 90


def test_analyze_ensemble_bounded_concurrency(client, monkeypatch):
    async def fake_score(job, profile_data):
        return {"score": 90, "pipeline": "ensemble"}

    monkeypatch.setattr(analyze, "score_job_ensemble", fake_score)
    monkeypatch.setattr(
        analyze, "settings", dataclasses.replace(analyze.settings, ensemble_job_concurrency=3)
    )

    jobs = [{"provider": "lever", "source_key": "acme", "job_id": str(i)} for i in range(3)]
    resp = client.post("/analyze/ensemble", json={"jobs": jobs})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 3
    assert [r["job_id"] for r in body["results"]] == ["0", "1", "2"]


def test_run_status_tracks_progress_and_completion(client, monkeypatch):
    async def fake_score(job, profile_data, model):
        if job["job_id"] == "bad":
            raise RuntimeError("boom")
        return {"score": 80, "pipeline": "maverick"}

    monkeypatch.setattr(analyze, "score_job_quick", fake_score)

    resp = client.post(
        "/analyze/quick",
        json={
            "jobs": [
                {"provider": "gh", "source_key": "acme", "job_id": "1"},
                {"provider": "gh", "source_key": "acme", "job_id": "bad"},
            ],
            "run_id": "run_status_test",
        },
    )
    assert resp.status_code == 200

    status_resp = client.get("/runs/run_status_test/status")
    assert status_resp.status_code == 200
    body = status_resp.json()
    assert body["status"] == "completed"
    assert body["phase"] == "done"
    assert body["job_count"] == 2
    assert body["processed_count"] == 2
    assert body["ok_count"] == 1
    assert body["error_count"] == 1


def test_run_status_unknown_run_returns_404(client):
    resp = client.get("/runs/does-not-exist/status")
    assert resp.status_code == 404


def test_cancel_run_unknown_returns_404(client):
    resp = client.post("/runs/does-not-exist/cancel")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cancel_run_cancels_the_active_task():
    task = asyncio.ensure_future(asyncio.sleep(100))
    analyze.active_tasks["run_cancel_me"] = task
    try:
        result = await analyze.cancel_run("run_cancel_me")
        assert result == {"ok": True}
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()
    finally:
        analyze.active_tasks.pop("run_cancel_me", None)


@pytest.mark.asyncio
async def test_analyze_quick_records_cancelled_status(monkeypatch, profile_dir):
    from services import profile as profile_service

    profile_service.load_profile(str(profile_dir))

    async def slow_score(job, profile_data, model):
        await asyncio.sleep(100)
        return {"score": 80, "pipeline": "maverick"}

    monkeypatch.setattr(analyze, "score_job_quick", slow_score)

    body = analyze.QuickAnalyzeRequest(
        jobs=[{"provider": "gh", "source_key": "acme", "job_id": "1"}],
        run_id="run_will_cancel",
    )

    async def _cancel_shortly():
        await asyncio.sleep(0.05)
        analyze.active_tasks["run_will_cancel"].cancel()

    cancel_task = asyncio.ensure_future(_cancel_shortly())
    response = await analyze.analyze_quick(body)
    await cancel_task

    assert response.results == [{"status": "error", "error": "cancelled"}]
    assert analyze.run_status["run_will_cancel"]["status"] == "cancelled"
    assert "run_will_cancel" not in analyze.active_tasks


def test_analyze_quick_returns_503_when_profile_not_loaded(client):
    from services.profile import invalidate_profile_cache

    invalidate_profile_cache()
    resp = client.post("/analyze/quick", json={"jobs": [{"title": "TPM"}]})
    assert resp.status_code == 503
    assert "CAREER_OPS_DIR" in resp.json()["detail"]
