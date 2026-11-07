import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from services import parser as parser_service

router = APIRouter(prefix="/parse")

PARSE_CONCURRENCY = 6


class ParseUrlRequest(BaseModel):
    url: str


class ParseBatchRequest(BaseModel):
    urls: list[str]


class ParseResult(BaseModel):
    url: str
    parsed: dict | None = None
    parse_error: str | None = None


class ParseBatchResponse(BaseModel):
    results: list[ParseResult]


async def _parse_one(url: str) -> ParseResult:
    try:
        parsed = await parser_service.parse_url(url)
        return ParseResult(url=url, parsed=parsed)
    except Exception as exc:
        return ParseResult(url=url, parse_error=str(exc))


@router.post("/url", response_model=ParseResult)
async def parse_url(body: ParseUrlRequest) -> ParseResult:
    return await _parse_one(body.url)


@router.post("/batch", response_model=ParseBatchResponse)
async def parse_batch(body: ParseBatchRequest) -> ParseBatchResponse:
    semaphore = asyncio.Semaphore(PARSE_CONCURRENCY)

    async def _bounded(url: str) -> ParseResult:
        async with semaphore:
            return await _parse_one(url)

    results = await asyncio.gather(*(_bounded(url) for url in body.urls))
    return ParseBatchResponse(results=list(results))
