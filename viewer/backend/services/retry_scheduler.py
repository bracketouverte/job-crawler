import asyncio
import json
import logging
from datetime import UTC, datetime

from services import queue_store
from services.match_run import execute_match_run_from_input, read_input_lines
from services.notifications import notify_discord_for_score

logger = logging.getLogger(__name__)

_POLL_INTERVAL_S = 10
_task: asyncio.Task | None = None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


async def _retry_discord_only(item: dict) -> None:
    subtasks = item.get("subtasks") or []
    discord_sub = next((s for s in subtasks if s.get("id") == "discord"), None)
    if discord_sub is None or not item.get("error"):
        return

    try:
        row = json.loads(item["error"])
    except ValueError:
        logger.error("retry_scheduler: invalid discord-only payload for %s", item.get("id"))
        return

    try:
        await notify_discord_for_score(row, item["id"])
        await queue_store.remove_queue_item(item["id"])
    except Exception as exc:
        err_msg = str(exc)
        next_attempt = item["attempt"] + 1
        is_permanent = next_attempt >= item["max_attempts"]
        await queue_store.upsert_queue_item(
            {
                **item,
                "attempt": next_attempt,
                "status": "permanent_error" if is_permanent else "retrying",
                "next_retry_at": None if is_permanent else queue_store.next_retry_at(next_attempt),
                "updated_at": _now_iso(),
                "error": err_msg,
                "subtasks": [
                    (
                        {**s, "status": "permanent_error" if is_permanent else "error", "error": err_msg}
                        if s.get("id") == "discord"
                        else s
                    )
                    for s in subtasks
                ],
            }
        )


async def _retry_match_run(item: dict) -> None:
    run_id = queue_store.run_id_from_item_id(item["id"])
    input_lines = await read_input_lines(run_id)
    if not input_lines:
        logger.error("retry_scheduler: no input file for run %s, skipping", run_id)
        return
    # On success execute_match_run_from_input updates the queue item to "done" itself.
    await execute_match_run_from_input(run_id, input_lines, item.get("mode") or "claude")


async def _tick() -> None:
    now = _now_iso()
    items = await queue_store.read_queue()
    due = [
        item
        for item in items
        if item.get("status") == "retrying" and item.get("next_retry_at") and item["next_retry_at"] <= now
    ]

    for item in due:
        # Mark as running before dispatch so a slow tick can't double-fire on the same item.
        item = {**item, "status": "running", "updated_at": _now_iso()}
        await queue_store.upsert_queue_item(item)

        subtasks = item.get("subtasks") or []
        is_discord_only = len(subtasks) == 1 and subtasks[0].get("id") == "discord"

        try:
            if is_discord_only:
                await _retry_discord_only(item)
            else:
                await _retry_match_run(item)
        except Exception:
            logger.exception("retry_scheduler: error processing item %s", item.get("id"))


async def _loop() -> None:
    while True:
        try:
            await _tick()
        except Exception:
            logger.exception("retry_scheduler: tick failed")
        await asyncio.sleep(_POLL_INTERVAL_S)


def start() -> asyncio.Task:
    global _task
    _task = asyncio.create_task(_loop())
    return _task


async def stop() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
