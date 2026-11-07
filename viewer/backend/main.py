import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

import config
from db import run_migrations
from routers.auto_analyzer import router as auto_analyzer_router
from routers.config_router import router as config_router
from routers.jobs import router as jobs_router
from routers.match_runs import router as match_runs_router
from routers.queue import router as queue_router
from services import matcher_client, retry_scheduler, saved_search
from services.match_run import mark_orphaned_runs_failed

logging.basicConfig(level=logging.INFO, format="[viewer] %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

STATIC_DIR = Path(config.STATIC_DIR)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path(config.MATCH_RUNS_DIR).mkdir(parents=True, exist_ok=True)
    logger.info("match runs dir ready: %s", config.MATCH_RUNS_DIR)

    await run_migrations()
    logger.info("migrations complete")

    matcher_client.start_client()

    await mark_orphaned_runs_failed()
    retry_scheduler.start()
    saved_search.start()

    yield

    await retry_scheduler.stop()
    await saved_search.stop()
    await matcher_client.stop_client()


app = FastAPI(title="viewer-service", lifespan=lifespan)
app.include_router(jobs_router)
app.include_router(match_runs_router)
app.include_router(queue_router)
app.include_router(auto_analyzer_router)
app.include_router(config_router)

if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

    @app.exception_handler(StarletteHTTPException)
    async def spa_fallback_handler(request, exc: StarletteHTTPException):
        if exc.status_code == 404 and not request.url.path.startswith("/api"):
            return FileResponse(STATIC_DIR / "index.html")
        return await http_exception_handler(request, exc)

else:
    logger.warning("static dir not found, skipping frontend mount: %s", STATIC_DIR)

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"status": "ok"}
