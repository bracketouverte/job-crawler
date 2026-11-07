import logging

import requests

import config

logger = logging.getLogger(__name__)


def send_failure_notification(error_msg: str) -> None:
    if not config.DISCORD_WEBHOOK_URL:
        return
    try:
        requests.post(
            config.DISCORD_WEBHOOK_URL,
            json={"embeds": [{"title": "Crawler failed", "description": (error_msg or "")[:500]}]},
            timeout=10,
        )
    except Exception:
        logger.exception("Failed to send Discord failure notification")
