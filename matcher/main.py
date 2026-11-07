import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from config import settings
from lib import llm_client
from routers.analyze import router as analyze_router
from routers.analyze import runs_router
from routers.parse import router as parse_router
from services import parser as parser_service
from services.profile import ProfileNotLoadedError, load_profile

logging.basicConfig(level=logging.INFO, format="[matcher] %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.profile_loaded = False
    app.state.profile_error = None

    try:
        load_profile(settings.career_ops_dir)
        app.state.profile_loaded = True
        logger.info("profile loaded from %s", settings.career_ops_dir)
    except Exception as exc:
        app.state.profile_error = str(exc)
        logger.warning("profile not loaded from %s: %s", settings.career_ops_dir, exc)

    llm_client.start_client()
    parser_service.start_client()

    yield

    await llm_client.stop_client()
    await parser_service.stop_client()


app = FastAPI(title="matcher-service", lifespan=lifespan)


@app.exception_handler(ProfileNotLoadedError)
async def profile_not_loaded_handler(_request: Request, exc: ProfileNotLoadedError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


router = APIRouter()


@router.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "profile_loaded": bool(app.state.profile_loaded),
    }


app.include_router(router)
app.include_router(analyze_router)
app.include_router(runs_router)
app.include_router(parse_router)
