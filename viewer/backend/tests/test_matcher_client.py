import httpx
import pytest

from services import matcher_client

pytestmark = pytest.mark.usefixtures("isolated_env")


def test_get_client_before_start_raises():
    matcher_client._client = None
    with pytest.raises(RuntimeError):
        matcher_client._get_client()


async def test_start_and_stop_client_lifecycle():
    matcher_client.start_client()
    assert matcher_client._client is not None
    await matcher_client.stop_client()
    assert matcher_client._client is None


async def test_parse_batch_posts_urls_and_returns_results(monkeypatch):
    matcher_client.start_client()
    try:

        async def fake_post(self, url, json=None, **kwargs):
            assert url == "/parse/batch"
            assert json == {"urls": ["https://x/1"]}
            return httpx.Response(
                200,
                json={"results": [{"url": "https://x/1", "parsed": {"title": "T"}, "parse_error": None}]},
                request=httpx.Request("POST", "http://matcher/parse/batch"),
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        results = await matcher_client.parse_batch(["https://x/1"])
        assert results[0]["parsed"]["title"] == "T"
    finally:
        await matcher_client.stop_client()


async def test_analyze_routes_ensemble_mode_to_ensemble_endpoint(monkeypatch):
    matcher_client.start_client()
    captured = {}
    try:

        async def fake_post(self, url, json=None, **kwargs):
            captured["url"] = url
            return httpx.Response(
                200,
                json={"results": [], "run_id": "run_1"},
                request=httpx.Request("POST", "http://matcher" + url),
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        await matcher_client.analyze("claude-ensemble", [{"job_id": "1"}], "run_1")
        assert captured["url"] == "/analyze/ensemble"
    finally:
        await matcher_client.stop_client()


async def test_analyze_routes_quick_mode_to_quick_endpoint(monkeypatch):
    matcher_client.start_client()
    captured = {}
    try:

        async def fake_post(self, url, json=None, **kwargs):
            captured["url"] = url
            return httpx.Response(
                200,
                json={"results": [], "run_id": "run_1"},
                request=httpx.Request("POST", "http://matcher" + url),
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        await matcher_client.analyze("claude", [{"job_id": "1"}], "run_1")
        assert captured["url"] == "/analyze/quick"
    finally:
        await matcher_client.stop_client()


async def test_cancel_run_returns_true_on_200(monkeypatch):
    matcher_client.start_client()
    try:

        async def fake_post(self, url, **kwargs):
            request = httpx.Request("POST", "http://matcher" + url)
            return httpx.Response(200, json={"ok": True}, request=request)

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        assert await matcher_client.cancel_run("run_1") is True
    finally:
        await matcher_client.stop_client()


async def test_cancel_run_returns_false_on_404(monkeypatch):
    matcher_client.start_client()
    try:

        async def fake_post(self, url, **kwargs):
            return httpx.Response(404, request=httpx.Request("POST", "http://matcher" + url))

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        assert await matcher_client.cancel_run("run_1") is False
    finally:
        await matcher_client.stop_client()


async def test_cancel_run_returns_false_on_network_error(monkeypatch):
    matcher_client.start_client()
    try:

        async def failing_post(self, url, **kwargs):
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(httpx.AsyncClient, "post", failing_post)
        assert await matcher_client.cancel_run("run_1") is False
    finally:
        await matcher_client.stop_client()


def test_read_timeout_covers_matcher_worst_case_single_job():
    # Matcher retries a job 3 times at a 180s read timeout, with 1s and 2s backoff between attempts.
    matcher_worst_case_seconds = 3 * 180 + 1 + 2
    matcher_client.start_client()
    try:
        assert matcher_client._client.timeout.read >= matcher_worst_case_seconds
    finally:
        matcher_client._client = None


async def test_analyze_surfaces_matcher_503_detail_message(monkeypatch):
    matcher_client.start_client()
    detail = "Profile not loaded: check that CAREER_OPS_DIR points to a directory"
    try:

        async def fake_post(self, url, json=None, **kwargs):
            return httpx.Response(
                503,
                json={"detail": detail},
                request=httpx.Request("POST", "http://matcher" + url),
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        with pytest.raises(RuntimeError) as exc_info:
            await matcher_client.analyze("claude", [{"job_id": "1"}], "run_1")
        assert str(exc_info.value) == detail
    finally:
        await matcher_client.stop_client()


async def test_analyze_non_string_detail_keeps_http_status_error(monkeypatch):
    matcher_client.start_client()
    try:

        async def fake_post(self, url, json=None, **kwargs):
            return httpx.Response(
                422,
                json={"detail": [{"loc": ["body", "jobs"], "msg": "field required"}]},
                request=httpx.Request("POST", "http://matcher" + url),
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        with pytest.raises(httpx.HTTPStatusError):
            await matcher_client.analyze("claude", [{"job_id": "1"}], "run_1")
    finally:
        await matcher_client.stop_client()
