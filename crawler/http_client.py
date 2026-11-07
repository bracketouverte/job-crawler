"""Shared HTTP fetch layer.

Ported from crawler/src/http.ts. Retry loop, backoff formula, transient
status set, and User-Agent rotation are kept verbatim; only the async
mechanics change shape (httpx.AsyncClient instead of fetch/AbortController).
"""

import asyncio
import random

import httpx

TRANSIENT_STATUSES = {408, 425, 429, 500, 502, 503, 504}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/144.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/144.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:147.0) Gecko/20100101 Firefox/147.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:147.0) Gecko/20100101 Firefox/147.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/26.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/144.0.0.0 Safari/537.36 Edg/144.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:147.0) Gecko/20100101 Firefox/147.0",
]


class HttpError(Exception):
    def __init__(self, message: str, status: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status = status
        self.body = body


def _random_ua() -> str:
    return random.choice(USER_AGENTS)


def _backoff_s(attempt: int) -> float:
    """Exponential backoff with +-20% random jitter, in seconds."""
    base_ms = min(5000, 250 * 2**attempt)
    jittered_ms = base_ms * (0.8 + random.random() * 0.4)
    return jittered_ms / 1000


class HttpClient:
    """A configured client — timeout/retries/jitter are fixed per instance,
    mirroring http.ts's createHttpClient(options) closure."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        timeout_s: float,
        retries: int,
        jitter_ms: tuple[int, int] | None = None,
    ):
        self._client = client
        self._timeout_s = timeout_s
        self._retries = retries
        self._jitter_ms = jitter_ms

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        if self._jitter_ms:
            lo, hi = self._jitter_ms
            await _sleep_s((lo + random.random() * (hi - lo)) / 1000)

        last_error: Exception | None = None
        for attempt in range(self._retries + 1):
            headers = {"User-Agent": _random_ua(), **kwargs.pop("headers", {})}
            try:
                response = await self._client.request(
                    method, url, timeout=self._timeout_s, headers=headers, **kwargs
                )
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt >= self._retries:
                    raise TimeoutError(f"Timeout while fetching {url}") from exc
                await _sleep_s(_backoff_s(attempt))
                continue
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt >= self._retries:
                    raise
                await _sleep_s(_backoff_s(attempt))
                continue

            if response.status_code >= 400:
                body = ""
                try:
                    body = response.text
                except Exception:
                    pass
                error = HttpError(f"HTTP {response.status_code} for {url}", response.status_code, body)
                if attempt < self._retries and response.status_code in TRANSIENT_STATUSES:
                    await _sleep_s(_backoff_s(attempt))
                    continue
                raise error

            return response

        # Unreachable — the loop above always returns or raises on the last
        # attempt — but keeps type-checkers happy about the return path.
        if last_error is not None:
            raise last_error
        raise HttpError(f"Exhausted retries for {url}")

    async def get_json(self, url: str, **kwargs):
        response = await self._request("GET", url, **kwargs)
        return response.json()

    async def post_json(self, url: str, body, **kwargs):
        headers = {"Content-Type": "application/json", **kwargs.pop("headers", {})}
        response = await self._request("POST", url, json=body, headers=headers, **kwargs)
        return response.json()

    async def get_text(self, url: str, **kwargs) -> str:
        response = await self._request("GET", url, **kwargs)
        return response.text


async def _sleep_s(seconds: float) -> None:
    await asyncio.sleep(seconds)
