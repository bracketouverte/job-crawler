import asyncio
import copy
import os

import httpx

DEFAULT_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
MAX_ATTEMPTS = 3

_client: httpx.AsyncClient | None = None


def start_client() -> None:
    global _client
    # httpx.Timeout requires either a default for all four phases or every
    # phase set explicitly; connect=10/read=180 with write/pool inherited
    # from the default (180) matches the story's spec without hitting that.
    _client = httpx.AsyncClient(timeout=httpx.Timeout(180, connect=10))


async def stop_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _get_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("llm_client not started — call start_client() in app lifespan")
    return _client


def chat_completions_url() -> str:
    explicit_url = os.environ.get("NVIDIA_CHAT_COMPLETIONS_URL") or os.environ.get(
        "NVIDIA_NIM_CHAT_COMPLETIONS_URL"
    )
    if explicit_url:
        return explicit_url.strip().rstrip("/")

    base_url = (
        (
            os.environ.get("NVIDIA_BASE_URL")
            or os.environ.get("NVIDIA_NIM_BASE_URL")
            or DEFAULT_NVIDIA_BASE_URL
        )
        .strip()
        .rstrip("/")
    )
    if base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url}/chat/completions"


def strip_cache_control(messages: list[dict]) -> list[dict]:
    """Returns a new list with `cache_control` removed from any message dict
    (Mistral rejects the field) — does not mutate the input."""
    stripped = []
    for message in messages:
        if "cache_control" in message:
            message = {k: v for k, v in message.items() if k != "cache_control"}
        stripped.append(message)
    return stripped


class RetryableHttpError(Exception):
    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


async def chat_completions(
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    response_format: dict | None = None,
    extra_body: dict | None = None,
) -> str:
    url = chat_completions_url()
    payload: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        payload["response_format"] = response_format
    if "nemotron-super" in model:
        payload["nvext"] = {"thinking": "on"}
    if extra_body:
        payload = {**payload, **copy.deepcopy(extra_body)}

    headers = {
        "Authorization": f"Bearer {os.environ.get('NVIDIA_API_KEY', '')}",
        "Content-Type": "application/json",
    }

    client = _get_client()
    last_exc: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code >= 500 or response.status_code == 429:
                raise RetryableHttpError(response.status_code)
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            if content is None:
                raise ValueError(f"model {model} returned empty content")
            return content
        except (httpx.TimeoutException, httpx.ConnectError, RetryableHttpError) as exc:
            last_exc = exc
            if attempt == MAX_ATTEMPTS:
                raise
            await asyncio.sleep(2 ** (attempt - 1))

    # Unreachable — the loop above always either returns or raises on the
    # last attempt — but keeps type-checkers happy about the return path.
    raise last_exc or RuntimeError("chat_completions failed with no captured exception")
