import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from services import queue_store
from services.match_run import (
    STATUS_FAILED,
    STATUS_RUNNING,
    cancel_run,
    execute_match_run_from_input,
    read_input_lines,
    read_manifest,
    write_manifest,
)

router = APIRouter(prefix="/api")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


async def _find_item(item_id: str) -> dict:
    items = await queue_store.read_queue()
    item = next((i for i in items if i.get("id") == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Queue item not found")
    return item


@router.get("/queue")
async def list_queue() -> list[dict]:
    return await queue_store.read_queue()


@router.post("/queue/{item_id}/retry")
async def retry_queue_item(item_id: str) -> dict:
    item = await _find_item(item_id)

    subtasks = item.get("subtasks") or []
    is_discord_only = len(subtasks) == 1 and subtasks[0].get("id") == "discord"
    if is_discord_only:
        item = {**item, "status": "retrying", "next_retry_at": _now_iso(), "updated_at": _now_iso()}
        await queue_store.upsert_queue_item(item)
        return item

    run_id = queue_store.run_id_from_item_id(item_id)
    input_lines = await read_input_lines(run_id)

    item = {
        **item,
        "attempt": 0,
        "status": "todo",
        "next_retry_at": None,
        "error": None,
        "updated_at": _now_iso(),
    }
    await queue_store.upsert_queue_item(item)

    asyncio.create_task(execute_match_run_from_input(run_id, input_lines, item.get("mode") or "claude"))

    return item


@router.post("/queue/{item_id}/stop")
async def stop_queue_item(item_id: str) -> dict:
    item = await _find_item(item_id)

    run_id = queue_store.run_id_from_item_id(item_id)
    await cancel_run(run_id)

    now = _now_iso()
    item = {
        **item,
        "status": "permanent_error",
        "updated_at": now,
        "subtasks": [
            {**s, "status": "error"} if s.get("status") in ("todo", "running") else s
            for s in item.get("subtasks", [])
        ],
    }
    await queue_store.upsert_queue_item(item)

    manifest = await read_manifest(run_id)
    if manifest is not None and manifest.get("status") == STATUS_RUNNING:
        manifest = {**manifest, "status": STATUS_FAILED, "error": "stopped by user", "updated_at": now}
        await write_manifest(run_id, manifest)

    return item


@router.post("/queue/{item_id}/restart")
async def restart_queue_item(item_id: str) -> dict:
    item = await _find_item(item_id)

    run_id = queue_store.run_id_from_item_id(item_id)
    await cancel_run(run_id)

    now = _now_iso()
    item = {
        **item,
        "status": "todo",
        "attempt": 1,
        "created_at": now,
        "updated_at": now,
        "error": None,
        "next_retry_at": None,
        "subtasks": [
            {**s, "status": "todo", "error": None, "started_at": None, "finished_at": None}
            for s in item.get("subtasks", [])
        ],
    }
    await queue_store.upsert_queue_item(item)

    input_lines = await read_input_lines(run_id)
    asyncio.create_task(execute_match_run_from_input(run_id, input_lines, item.get("mode") or "claude"))

    return item


@router.delete("/queue/{item_id}")
async def delete_queue_item(item_id: str) -> dict:
    await queue_store.remove_queue_item(item_id)
    return {"ok": True}
