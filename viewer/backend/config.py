import os
from pathlib import Path

CATALOG_DB = os.environ.get("CATALOG_DB", "/app/state/catalog.sqlite")
STATE_DIR = os.environ.get("STATE_DIR", str(Path(CATALOG_DB).parent))
MATCH_RUNS_DIR = os.environ.get("MATCH_RUNS_DIR", str(Path(STATE_DIR) / "match-runs"))
ANALYSIS_CACHE_PATH = os.environ.get("ANALYSIS_CACHE_PATH", str(Path(STATE_DIR) / "job-analysis-cache.json"))

NVIDIA_MODEL = os.environ.get("NVIDIA_MODEL", "meta/llama-4-maverick-17b-128e-instruct")
NVIDIA_ENSEMBLE_SCORERS = os.environ.get("NVIDIA_ENSEMBLE_SCORERS")
NVIDIA_ENSEMBLE_SYNTHESIZER = os.environ.get("NVIDIA_ENSEMBLE_SYNTHESIZER")

MATCHER_SERVICE_URL = os.environ.get("MATCHER_SERVICE_URL", "http://matcher:8001")

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
SCORE_NOTIFY_MIN_SCORE = int(os.environ.get("SCORE_NOTIFY_MIN_SCORE", "4"))

PORT = int(os.environ.get("PORT", "3000"))

LOGO_DEV_PUBLISHABLE_KEY = os.environ.get("LOGO_DEV_PUBLISHABLE_KEY")
LOGO_DEV_SECRET_KEY = os.environ.get("LOGO_DEV_SECRET_KEY")
USER_LOCATION = os.environ.get("USER_LOCATION")

SAVED_SEARCH_ANALYZER_ENABLED = os.environ.get("SAVED_SEARCH_ANALYZER_ENABLED", "1") != "0"
SAVED_SEARCH_ANALYZER_INTERVAL_MS = int(os.environ.get("SAVED_SEARCH_ANALYZER_INTERVAL_MS", "60000"))

SKIP_TIERS = os.environ.get("SKIP_TIERS", "intern")

HIDDEN_JOBS_PATH = os.environ.get("HIDDEN_JOBS_PATH", str(Path(STATE_DIR) / "hidden-jobs.json"))
SCORE_NOTIFICATIONS_PATH = os.environ.get(
    "SCORE_NOTIFICATIONS_PATH", str(Path(STATE_DIR) / "score-notifications.json")
)
CRAWLER_ACTIVE_LOCK_PATH = os.environ.get(
    "CRAWLER_ACTIVE_LOCK_PATH", str(Path(STATE_DIR) / "crawler-active.lock")
)
CRAWLER_ACTIVE_LOCK_STALE_MS = int(os.environ.get("CRAWLER_ACTIVE_LOCK_STALE_MS", "7200000"))
CRAWLER_PROGRESS_PATH = os.environ.get(
    "CRAWLER_PROGRESS_PATH", str(Path(STATE_DIR) / "crawler-progress.json")
)

_BACKEND_DIR = Path(__file__).resolve().parent
SAVED_SEARCHES_PATH = os.environ.get(
    "SAVED_SEARCHES_PATH", str(_BACKEND_DIR.parent / "frontend" / "public" / "saved-searches.json")
)
STATIC_DIR = os.environ.get("STATIC_DIR", str(_BACKEND_DIR.parent / "frontend" / "dist"))
