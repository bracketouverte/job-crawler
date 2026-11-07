import httpx
import pytest

from lib import llm_client


def test_chat_completions_url_default(monkeypatch):
    monkeypatch.delenv("NVIDIA_CHAT_COMPLETIONS_URL", raising=False)
    monkeypatch.delenv("NVIDIA_NIM_CHAT_COMPLETIONS_URL", raising=False)
    monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)
    monkeypatch.delenv("NVIDIA_NIM_BASE_URL", raising=False)
    assert llm_client.chat_completions_url() == "https://integrate.api.nvidia.com/v1/chat/completions"


def test_chat_completions_url_explicit_override(monkeypatch):
    monkeypatch.setenv("NVIDIA_CHAT_COMPLETIONS_URL", "https://example.com/custom/ ")
    assert llm_client.chat_completions_url() == "https://example.com/custom"


def test_chat_completions_url_base_already_has_suffix(monkeypatch):
    monkeypatch.delenv("NVIDIA_CHAT_COMPLETIONS_URL", raising=False)
    monkeypatch.delenv("NVIDIA_NIM_CHAT_COMPLETIONS_URL", raising=False)
    monkeypatch.setenv("NVIDIA_BASE_URL", "https://example.com/v1/chat/completions")
    assert llm_client.chat_completions_url() == "https://example.com/v1/chat/completions"


def test_strip_cache_control_removes_field_without_mutating_input():
    messages = [{"role": "system", "content": "x", "cache_control": {"type": "ephemeral"}}]
    stripped = llm_client.strip_cache_control(messages)
    assert "cache_control" not in stripped[0]
    assert "cache_control" in messages[0]


@pytest.mark.asyncio
async def test_chat_completions_success(monkeypatch):
    llm_client.start_client()
    try:

        async def fake_post(self, url, json=None, headers=None):
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "hello"}}]}, request=httpx.Request("POST", url)
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        result = await llm_client.chat_completions(
            model="meta/llama-4-maverick-17b-128e-instruct",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.2,
            max_tokens=100,
        )
        assert result == "hello"
    finally:
        await llm_client.stop_client()


@pytest.mark.asyncio
async def test_chat_completions_nemotron_adds_thinking_extension(monkeypatch):
    llm_client.start_client()
    captured = {}
    try:

        async def fake_post(self, url, json=None, headers=None):
            captured["payload"] = json
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "ok"}}]}, request=httpx.Request("POST", url)
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        await llm_client.chat_completions(
            model="nvidia/llama-3.3-nemotron-super-49b-v1.5",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.1,
            max_tokens=100,
        )
        assert captured["payload"]["nvext"] == {"thinking": "on"}
    finally:
        await llm_client.stop_client()


@pytest.mark.asyncio
async def test_chat_completions_retries_then_succeeds_on_500(monkeypatch):
    llm_client.start_client()
    attempts = {"n": 0}
    try:

        async def fake_post(self, url, json=None, headers=None):
            attempts["n"] += 1
            if attempts["n"] < 2:
                return httpx.Response(500)
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "recovered"}}]},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        monkeypatch.setattr("asyncio.sleep", lambda *_a, **_k: _instant_sleep())
        result = await llm_client.chat_completions(
            model="meta/llama-4-maverick-17b-128e-instruct",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.2,
            max_tokens=100,
        )
        assert result == "recovered"
        assert attempts["n"] == 2
    finally:
        await llm_client.stop_client()


@pytest.mark.asyncio
async def test_chat_completions_exhausts_retries_and_raises(monkeypatch):
    llm_client.start_client()
    try:

        async def fake_post(self, url, json=None, headers=None):
            return httpx.Response(500)

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        monkeypatch.setattr("asyncio.sleep", lambda *_a, **_k: _instant_sleep())
        with pytest.raises(llm_client.RetryableHttpError):
            await llm_client.chat_completions(
                model="meta/llama-4-maverick-17b-128e-instruct",
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.2,
                max_tokens=100,
            )
    finally:
        await llm_client.stop_client()


@pytest.mark.asyncio
async def test_chat_completions_retries_then_succeeds_on_429(monkeypatch):
    llm_client.start_client()
    attempts = {"n": 0}
    try:

        async def fake_post(self, url, json=None, headers=None):
            attempts["n"] += 1
            if attempts["n"] < 2:
                return httpx.Response(429, request=httpx.Request("POST", url))
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "recovered"}}]},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        monkeypatch.setattr("asyncio.sleep", lambda *_a, **_k: _instant_sleep())
        result = await llm_client.chat_completions(
            model="openai/gpt-oss-20b",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.2,
            max_tokens=100,
        )
        assert result == "recovered"
        assert attempts["n"] == 2
    finally:
        await llm_client.stop_client()


@pytest.mark.asyncio
async def test_chat_completions_null_content_raises_clear_error(monkeypatch):
    llm_client.start_client()
    try:

        async def fake_post(self, url, json=None, headers=None):
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": None}}]},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        with pytest.raises(ValueError, match="empty content"):
            await llm_client.chat_completions(
                model="nvidia/nemotron-3.5-lightning-30b-a3b",
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.2,
                max_tokens=100,
            )
    finally:
        await llm_client.stop_client()


async def _instant_sleep():
    return None


def test_get_client_before_start_raises():
    llm_client._client = None
    with pytest.raises(RuntimeError):
        llm_client._get_client()
