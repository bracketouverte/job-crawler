import logging
import subprocess
from datetime import UTC, datetime

import config
import state
from notifications import send_failure_notification

logger = logging.getLogger(__name__)

# Crawls can legitimately run long (thousands of ATS pages); this bounds a
# genuinely hung run without cutting off a slow-but-healthy one.
CRAWLER_TIMEOUT_S = 3600


def run_crawler() -> None:
    logger.info("Triggering crawler...")
    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                f"{config.PROJECT_DIR}/docker-compose.yml",
                "--project-directory",
                config.PROJECT_DIR,
                "run",
                "--rm",
                config.CRAWLER_SERVICE_NAME,
            ],
            capture_output=True,
            text=True,
            timeout=CRAWLER_TIMEOUT_S,
            check=True,
        )
        logger.info("Crawler done.")
        if result.stdout:
            logger.info("Crawler stdout (tail): %s", result.stdout[-2000:])
    except subprocess.CalledProcessError as exc:
        logger.error("Crawler failed (exit %s): %s", exc.returncode, exc.stderr)
        send_failure_notification(exc.stderr or f"Crawler exited with code {exc.returncode}")
    except subprocess.TimeoutExpired as exc:
        logger.error("Crawler timed out after %ss", CRAWLER_TIMEOUT_S)
        send_failure_notification(f"Crawler timed out after {CRAWLER_TIMEOUT_S}s: {exc}")
    except OSError as exc:
        # e.g. the docker CLI binary itself is missing or unreachable —
        # distinct from the crawler container running and failing.
        logger.error("Could not invoke docker: %s", exc)
        send_failure_notification(f"Could not invoke docker: {exc}")
    finally:
        # Record the run on both success and failure — a crash must not
        # bypass the debounce guard on the next scheduled tick.
        state.record_run(now_iso)
