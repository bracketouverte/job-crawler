import pytest
from fastapi.testclient import TestClient

import main
from routers import parse as parse_router
from services import parser as parser_service


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def test_parse_url_success(client, monkeypatch):
    async def fake_parse_url(url):
        return {"title": "Senior TPM", "provider": "greenhouse"}

    monkeypatch.setattr(parser_service, "parse_url", fake_parse_url)

    resp = client.post("/parse/url", json={"url": "https://boards.greenhouse.io/acme/jobs/123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["parsed"]["title"] == "Senior TPM"
    assert body["parse_error"] is None


def test_parse_url_failure_returns_200_with_error(client, monkeypatch):
    async def fake_parse_url(url):
        raise ValueError("Unsupported provider for URL")

    monkeypatch.setattr(parser_service, "parse_url", fake_parse_url)

    resp = client.post("/parse/url", json={"url": "https://example.com/careers/random"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["parsed"] is None
    assert "Unsupported provider" in body["parse_error"]


def test_parse_batch_mixed_results(client, monkeypatch):
    async def fake_parse_url(url):
        if "bad" in url:
            raise ValueError("boom")
        return {"title": "Senior TPM", "url": url}

    monkeypatch.setattr(parser_service, "parse_url", fake_parse_url)

    resp = client.post(
        "/parse/batch",
        json={"urls": ["https://good.example.com/1", "https://bad.example.com/2"]},
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) == 2
    by_url = {r["url"]: r for r in results}
    assert by_url["https://good.example.com/1"]["parse_error"] is None
    assert by_url["https://bad.example.com/2"]["parse_error"] == "boom"


def test_parse_batch_respects_concurrency_cap(monkeypatch):
    assert parse_router.PARSE_CONCURRENCY == 6
