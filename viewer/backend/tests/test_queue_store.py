import asyncio
import json

import pytest

from services import queue_store


@pytest.fixture(autouse=True)
def _env(isolated_env):
    return isolated_env


async def test_read_queue_missing_file_returns_empty():
    assert await queue_store.read_queue() == []


async def test_write_and_read_round_trip():
    items = [{"id": "a"}, {"id": "b"}]
    await queue_store.write_queue(items)
    assert await queue_store.read_queue() == items


async def test_write_queue_is_atomic_tmp_rename(isolated_env):
    await queue_store.write_queue([{"id": "a"}])
    path = queue_store.queue_path()
    assert path.exists()
    assert not path.with_name(f".{path.name}.tmp").exists()


async def test_upsert_inserts_new_item():
    await queue_store.upsert_queue_item({"id": "a", "status": "todo"})
    items = await queue_store.read_queue()
    assert items == [{"id": "a", "status": "todo"}]


async def test_upsert_replaces_existing_item_in_place():
    await queue_store.upsert_queue_item({"id": "a", "status": "todo"})
    await queue_store.upsert_queue_item({"id": "b", "status": "todo"})
    await queue_store.upsert_queue_item({"id": "a", "status": "done"})
    items = await queue_store.read_queue()
    assert [i["id"] for i in items] == ["a", "b"]
    assert items[0]["status"] == "done"


async def test_remove_queue_item():
    await queue_store.upsert_queue_item({"id": "a"})
    await queue_store.upsert_queue_item({"id": "b"})
    await queue_store.remove_queue_item("a")
    items = await queue_store.read_queue()
    assert [i["id"] for i in items] == ["b"]


async def test_concurrent_upserts_do_not_corrupt_file():
    await asyncio.gather(*(queue_store.upsert_queue_item({"id": f"item{i}"}) for i in range(20)))
    items = await queue_store.read_queue()
    assert len(items) == 20
    assert {i["id"] for i in items} == {f"item{i}" for i in range(20)}


def test_run_id_from_item_id_splits_on_first_colon_only():
    assert queue_store.run_id_from_item_id("run_1:provider|source:key|1") == "run_1"


def test_run_id_from_item_id_no_colon():
    assert queue_store.run_id_from_item_id("no-colon") == "no-colon"


def test_build_subtasks_ensemble_has_three():
    subtasks = queue_store.build_subtasks("claude-ensemble")
    assert len(subtasks) == 3
    ids = [s["id"] for s in subtasks]
    assert ids == ["parse", "score", "discord"]
    assert all(s["status"] == "todo" for s in subtasks)
    assert next(s for s in subtasks if s["id"] == "score")["label"] == "Ensemble score"


def test_build_subtasks_quick_has_three():
    subtasks = queue_store.build_subtasks("claude")
    assert len(subtasks) == 3
    ids = [s["id"] for s in subtasks]
    assert ids == ["parse", "score", "discord"]
    assert next(s for s in subtasks if s["id"] == "score")["label"] == "Score"


def test_retry_backoff_seconds_formula():
    assert queue_store.retry_backoff_seconds(2) == 120
    assert queue_store.retry_backoff_seconds(3) == 240


def test_next_retry_at_is_iso_z_suffixed_future_timestamp():
    result = queue_store.next_retry_at(2)
    assert result.endswith("Z")
    assert "T" in result


async def test_write_queue_pretty_printed_with_trailing_newline(isolated_env):
    await queue_store.write_queue([{"id": "a"}])
    raw = queue_store.queue_path().read_text()
    assert raw.endswith("\n")
    parsed = json.loads(raw)
    assert parsed == [{"id": "a"}]
