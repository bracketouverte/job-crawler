import httpx
import pytest

from http_client import TRANSIENT_STATUSES, USER_AGENTS, HttpClient, HttpError


@pytest.fixture
async def async_client():
    async with httpx.AsyncClient() as client:
        yield client


def _response(status: int, text: str = "", request: httpx.Request | None = None) -> httpx.Response:
    return httpx.Response(status, text=text, request=request or httpx.Request("GET", "http://x/"))


@pytest.mark.asyncio
async def test_get_json_success_no_retry(async_client, monkeypatch):
    calls = []

    async def fake_request(self, method, url, **kwargs):
        calls.append(1)
        return httpx.Response(200, json={"ok": True}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    client = HttpClient(async_client, timeout_s=5, retries=2)
    result = await client.get_json("http://example.com")
    assert result == {"ok": True}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_non_transient_status_raises_immediately_without_retry(async_client, monkeypatch):
    calls = []

    async def fake_request(self, method, url, **kwargs):
        calls.append(1)
        return _response(404, "not found")

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    client = HttpClient(async_client, timeout_s=5, retries=3)
    with pytest.raises(HttpError) as exc_info:
        await client.get_json("http://example.com")
    assert exc_info.value.status == 404
    assert exc_info.value.body == "not found"
    assert len(calls) == 1  # no retry for a non-transient status


@pytest.mark.asyncio
@pytest.mark.parametrize("status", sorted(TRANSIENT_STATUSES))
async def test_transient_status_is_retried_up_to_retries_then_raises(async_client, monkeypatch, status):
    calls = []

    async def fake_request(self, method, url, **kwargs):
        calls.append(1)
        return _response(status)

    async def instant_sleep(*_a, **_k):
        return None

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    monkeypatch.setattr("http_client._sleep_s", instant_sleep)
    client = HttpClient(async_client, timeout_s=5, retries=2)
    with pytest.raises(HttpError) as exc_info:
        await client.get_json("http://example.com")
    assert exc_info.value.status == status
    assert len(calls) == 3  # initial attempt + 2 retries


@pytest.mark.asyncio
async def test_transient_status_recovers_on_retry(async_client, monkeypatch):
    attempts = {"n": 0}

    async def fake_request(self, method, url, **kwargs):
        attempts["n"] += 1
        if attempts["n"] < 2:
            return _response(503)
        return httpx.Response(200, json={"ok": True}, request=httpx.Request(method, url))

    async def instant_sleep(*_a, **_k):
        return None

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    monkeypatch.setattr("http_client._sleep_s", instant_sleep)
    client = HttpClient(async_client, timeout_s=5, retries=2)
    result = await client.get_json("http://example.com")
    assert result == {"ok": True}
    assert attempts["n"] == 2


@pytest.mark.asyncio
async def test_timeout_is_retried_then_raises(async_client, monkeypatch):
    calls = []

    async def fake_request(self, method, url, **kwargs):
        calls.append(1)
        raise httpx.ReadTimeout("timed out")

    async def instant_sleep(*_a, **_k):
        return None

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    monkeypatch.setattr("http_client._sleep_s", instant_sleep)
    client = HttpClient(async_client, timeout_s=5, retries=1)
    with pytest.raises(TimeoutError, match="Timeout while fetching"):
        await client.get_json("http://example.com")
    assert len(calls) == 2  # initial attempt + 1 retry


@pytest.mark.asyncio
async def test_connection_error_is_retried_then_raised(async_client, monkeypatch):
    calls = []

    async def fake_request(self, method, url, **kwargs):
        calls.append(1)
        raise httpx.ConnectError("connection refused")

    async def instant_sleep(*_a, **_k):
        return None

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    monkeypatch.setattr("http_client._sleep_s", instant_sleep)
    client = HttpClient(async_client, timeout_s=5, retries=1)
    with pytest.raises(httpx.ConnectError):
        await client.get_json("http://example.com")
    assert len(calls) == 2  # initial attempt + 1 retry


@pytest.mark.asyncio
async def test_sleep_s_actually_sleeps():
    from http_client import _sleep_s

    await _sleep_s(0)  # exercises the real asyncio.sleep call path


@pytest.mark.asyncio
async def test_jitter_delays_once_before_retry_loop(async_client, monkeypatch):
    sleep_calls = []

    async def fake_request(self, method, url, **kwargs):
        return httpx.Response(200, json={}, request=httpx.Request(method, url))

    async def recording_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    monkeypatch.setattr("http_client._sleep_s", recording_sleep)
    client = HttpClient(async_client, timeout_s=5, retries=2, jitter_ms=(300, 1200))
    await client.get_json("http://example.com")
    assert len(sleep_calls) == 1
    assert 0.3 <= sleep_calls[0] <= 1.2


@pytest.mark.asyncio
async def test_post_json_sends_content_type_and_body(async_client, monkeypatch):
    captured = {}

    async def fake_request(self, method, url, **kwargs):
        captured["method"] = method
        captured["json"] = kwargs.get("json")
        captured["headers"] = kwargs.get("headers")
        return httpx.Response(200, json={"ok": True}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    client = HttpClient(async_client, timeout_s=5, retries=0)
    await client.post_json("http://example.com", {"a": 1})
    assert captured["method"] == "POST"
    assert captured["json"] == {"a": 1}
    assert captured["headers"]["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_get_text_returns_body_text(async_client, monkeypatch):
    async def fake_request(self, method, url, **kwargs):
        return httpx.Response(200, text="hello world", request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    client = HttpClient(async_client, timeout_s=5, retries=0)
    result = await client.get_text("http://example.com")
    assert result == "hello world"


@pytest.mark.asyncio
async def test_user_agent_header_is_set_from_rotation_list(async_client, monkeypatch):
    captured = {}

    async def fake_request(self, method, url, **kwargs):
        captured["ua"] = kwargs.get("headers", {}).get("User-Agent")
        return httpx.Response(200, json={}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    client = HttpClient(async_client, timeout_s=5, retries=0)
    await client.get_json("http://example.com")
    assert captured["ua"] in USER_AGENTS
