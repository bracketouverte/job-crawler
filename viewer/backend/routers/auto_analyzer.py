from fastapi import APIRouter
from pydantic import BaseModel

import config
from services import saved_search

router = APIRouter(prefix="/api")


class AutoAnalyzerBody(BaseModel):
    paused: bool


def _state() -> dict:
    return {
        "enabled": config.SAVED_SEARCH_ANALYZER_ENABLED,
        "paused": saved_search.saved_search_analyzer_paused,
        "busy": saved_search.saved_search_analyzer_busy,
        "current": saved_search.saved_search_analyzer_current,
    }


@router.get("/auto-analyzer")
async def get_auto_analyzer() -> dict:
    return _state()


@router.post("/auto-analyzer")
async def post_auto_analyzer(body: AutoAnalyzerBody) -> dict:
    saved_search.set_paused(body.paused)
    return _state()
