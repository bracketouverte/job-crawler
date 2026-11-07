import os


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


TZ = os.environ.get("TZ", "America/New_York")
PROJECT_DIR = _env("PROJECT_DIR")
RUNS_FILE = os.environ.get("RUNS_FILE", "/state/scheduler-runs.json")
DEBOUNCE_MINUTES = int(os.environ.get("DEBOUNCE_MINUTES", "110"))
MAX_RUNS_HISTORY = int(os.environ.get("MAX_RUNS_HISTORY", "10"))
CRAWLER_SERVICE_NAME = os.environ.get("CRAWLER_SERVICE_NAME", "crawler")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
LOG_PATH = os.environ.get("LOG_PATH", "/var/log/scheduler.log")

# Schedule config — kept as constants, not env vars, per the rewrite plan.
WEEKDAY_HOURS = [8, 10, 12, 14, 16, 18, 20]  # Mon-Fri
SATURDAY_HOURS = [8, 14]
SUNDAY_HOURS = [8]
