import httpx

import config

_client: httpx.AsyncClient | None = None


def start_client() -> None:
    global _client
    _client = httpx.AsyncClient(base_url=config.MATCHER_SERVICE_URL, timeout=httpx.Timeout(600, connect=10))


async def stop_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _get_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("matcher_client not started — call start_client() in app lifespan")
    return _client


async def parse_batch(urls: list[str]) -> list[dict]:
    client = _get_client()
    response = await client.post("/parse/batch", json={"urls": urls})
    response.raise_for_status()
    return response.json()["results"]


async def analyze(mode: str, jobs: list[dict], run_id: str) -> list[dict]:
    client = _get_client()
    endpoint = "/analyze/ensemble" if mode == "claude-ensemble" else "/analyze/quick"
    response = await client.post(endpoint, json={"jobs": jobs, "run_id": run_id})
    if response.is_error:
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        if isinstance(detail, str) and detail:
            raise RuntimeError(detail)
    response.raise_for_status()
    return response.json()["results"]


async def cancel_run(run_id: str) -> bool:
    client = _get_client()
    try:
        response = await client.post(f"/runs/{run_id}/cancel")
    except httpx.HTTPError:
        return False
    return response.status_code == 200
