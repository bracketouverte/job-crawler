import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

import runner as runner_module
from config import CliOptions
from http_client import HttpError
from models import NormalizedJob, SourceEntry


def _write_source_file(sources_dir: Path, provider: str, companies: list[dict], **extra):
    payload = {"provider": provider, "companies": companies, **extra}
    (sources_dir / f"{provider}.json").write_text(json.dumps(payload))


def _options(tmp_path: Path, **overrides) -> CliOptions:
    defaults = dict(
        sources=str(tmp_path / "sources"),
        providers="all",
        concurrency=10,
        out=str(tmp_path / "out" / "jobs.jsonl"),
        report=str(tmp_path / "out" / "report.json"),
        catalog_db=str(tmp_path / "state" / "catalog.sqlite"),
        progress_every_ms=0,
        progress_file=str(tmp_path / "state" / "crawler-progress.json"),
        timeout_ms=1000,
        retries=0,
    )
    defaults.update(overrides)
    return CliOptions(**defaults)


class _FakeCrawler:
    def __init__(self, fn):
        self._fn = fn

    async def crawl(self, source, context):
        return await self._fn(source, context)


@pytest.mark.asyncio
async def test_writes_jsonl_and_report_isolating_failures(tmp_path, monkeypatch):
    (tmp_path / "sources").mkdir()
    _write_source_file(tmp_path / "sources", "lever", [{"identifier": "ok"}, {"identifier": "missing"}])

    async def crawl(source, context):
        if source.identifier == "ok":
            return [
                NormalizedJob(
                    provider="lever",
                    source_key="ok",
                    job_id="1",
                    fetched_at=context.fetched_at,
                    title="Engineer",
                )
            ]
        raise HttpError("not found", status=404)

    monkeypatch.setitem(runner_module.CRAWLER_BY_PROVIDER, "lever", _FakeCrawler(crawl))

    options = _options(tmp_path, providers="lever")
    report = await runner_module.run_crawler(options)

    jsonl = Path(options.out).read_text()
    assert "Engineer" in jsonl
    assert report.providers["lever"].succeeded == 1
    assert report.providers["lever"].failed == 1
    assert report.total_jobs == 1


@pytest.mark.asyncio
async def test_404_marks_slug_dead_and_still_appears_as_a_failure(tmp_path, monkeypatch):
    (tmp_path / "sources").mkdir()
    _write_source_file(tmp_path / "sources", "lever", [{"identifier": "gone"}])

    async def crawl(source, context):
        raise HttpError("gone", status=404)

    monkeypatch.setitem(runner_module.CRAWLER_BY_PROVIDER, "lever", _FakeCrawler(crawl))

    options = _options(tmp_path, providers="lever")
    report = await runner_module.run_crawler(options)

    assert report.providers["lever"].failed == 1
    assert report.failures[0].status == 404
    assert report.failures[0].provider == "lever"

    from dead_slugs import load_dead_slugs

    dead = load_dead_slugs(str(Path(options.catalog_db).parent), "lever")
    assert "gone" in dead


@pytest.mark.asyncio
async def test_500_does_not_mark_slug_dead(tmp_path, monkeypatch):
    (tmp_path / "sources").mkdir()
    _write_source_file(tmp_path / "sources", "lever", [{"identifier": "broken"}])

    async def crawl(source, context):
        raise HttpError("server error", status=500)

    monkeypatch.setitem(runner_module.CRAWLER_BY_PROVIDER, "lever", _FakeCrawler(crawl))

    options = _options(tmp_path, providers="lever")
    report = await runner_module.run_crawler(options)

    assert report.providers["lever"].failed == 1
    from dead_slugs import load_dead_slugs

    dead = load_dead_slugs(str(Path(options.catalog_db).parent), "lever")
    assert dead == set()


@pytest.mark.asyncio
async def test_skips_excluded_sources(tmp_path, monkeypatch):
    (tmp_path / "sources").mkdir()
    _write_source_file(tmp_path / "sources", "lever", [{"identifier": "ok"}, {"identifier": "excluded"}])

    exclude_file = tmp_path / "exclude.jsonl"
    exclude_file.write_text(json.dumps({"provider": "lever", "source_key": "excluded"}) + "\n")

    calls = []

    async def crawl(source, context):
        calls.append(source.identifier)
        return []

    monkeypatch.setitem(runner_module.CRAWLER_BY_PROVIDER, "lever", _FakeCrawler(crawl))

    options = _options(tmp_path, providers="lever", exclude_sources=str(exclude_file))
    report = await runner_module.run_crawler(options)

    assert calls == ["ok"]
    assert report.providers["lever"].skipped == 1


@pytest.mark.asyncio
async def test_skips_dead_slugs(tmp_path, monkeypatch):
    (tmp_path / "sources").mkdir()
    _write_source_file(tmp_path / "sources", "lever", [{"identifier": "ok"}, {"identifier": "dead"}])

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    from dead_slugs import mark_dead

    mark_dead(str(state_dir), "lever", "dead", 404)

    calls = []

    async def crawl(source, context):
        calls.append(source.identifier)
        return []

    monkeypatch.setitem(runner_module.CRAWLER_BY_PROVIDER, "lever", _FakeCrawler(crawl))

    options = _options(tmp_path, providers="lever", catalog_db=str(state_dir / "catalog.sqlite"))
    report = await runner_module.run_crawler(options)

    assert calls == ["ok"]
    assert report.providers["lever"].skipped == 1


@pytest.mark.asyncio
async def test_max_age_hours_filters_jsonl_but_not_catalog_db(tmp_path, monkeypatch):
    (tmp_path / "sources").mkdir()
    _write_source_file(tmp_path / "sources", "lever", [{"identifier": "ok"}])

    async def crawl(source, context):
        return [
            NormalizedJob(
                provider="lever",
                source_key="ok",
                job_id="1",
                fetched_at=context.fetched_at,
                posted_at="2020-01-01T00:00:00Z",
                title="Old Job",
            )
        ]

    monkeypatch.setitem(runner_module.CRAWLER_BY_PROVIDER, "lever", _FakeCrawler(crawl))

    options = _options(tmp_path, providers="lever", max_age_hours=24)
    await runner_module.run_crawler(options)

    assert Path(options.out).read_text().strip() == ""

    db = sqlite3.connect(options.catalog_db)
    row = db.execute("SELECT job_id FROM catalog_jobs").fetchone()
    db.close()
    assert row is not None
    assert row[0] == "1"


@pytest.mark.asyncio
async def test_dedupes_jobs_with_same_provider_source_key_job_id(tmp_path, monkeypatch):
    (tmp_path / "sources").mkdir()
    _write_source_file(tmp_path / "sources", "lever", [{"identifier": "a"}])

    async def crawl(source, context):
        return [
            NormalizedJob(
                provider="lever", source_key="a", job_id="1", fetched_at=context.fetched_at, title="First"
            ),
            NormalizedJob(
                provider="lever", source_key="a", job_id="1", fetched_at=context.fetched_at, title="Dup"
            ),
        ]

    monkeypatch.setitem(runner_module.CRAWLER_BY_PROVIDER, "lever", _FakeCrawler(crawl))

    options = _options(tmp_path, providers="lever")
    report = await runner_module.run_crawler(options)

    lines = [line for line in Path(options.out).read_text().splitlines() if line.strip()]
    assert len(lines) == 1
    assert report.providers["lever"].jobs == 1


@pytest.mark.asyncio
async def test_jsonl_lines_omit_skill_tier_key_when_unset(tmp_path, monkeypatch):
    (tmp_path / "sources").mkdir()
    _write_source_file(tmp_path / "sources", "lever", [{"identifier": "a"}])

    async def crawl(source, context):
        return [NormalizedJob(provider="lever", source_key="a", job_id="1", fetched_at=context.fetched_at)]

    monkeypatch.setitem(runner_module.CRAWLER_BY_PROVIDER, "lever", _FakeCrawler(crawl))

    options = _options(tmp_path, providers="lever")
    await runner_module.run_crawler(options)

    line = json.loads(Path(options.out).read_text().splitlines()[0])
    assert "skill_tier" not in line


@pytest.mark.asyncio
async def test_progress_payload_shape_matches_viewer_contract(tmp_path, monkeypatch):
    (tmp_path / "sources").mkdir()
    _write_source_file(tmp_path / "sources", "lever", [{"identifier": "a"}])

    async def crawl(source, context):
        return [NormalizedJob(provider="lever", source_key="a", job_id="1", fetched_at=context.fetched_at)]

    monkeypatch.setitem(runner_module.CRAWLER_BY_PROVIDER, "lever", _FakeCrawler(crawl))

    options = _options(tmp_path, providers="lever")
    await runner_module.run_crawler(options)

    payload = json.loads(Path(options.progress_file).read_text())
    assert set(payload.keys()) == {
        "event",
        "elapsed_seconds",
        "completed_sources",
        "total_sources",
        "percent",
        "succeeded_sources",
        "failed_sources",
        "total_jobs",
        "failures_recorded",
        "by_provider",
    }
    assert payload["event"] == "done"
    provider_entry = payload["by_provider"]["lever"]
    assert set(provider_entry.keys()) == {"done", "total", "skipped", "jobs", "failed"}


@pytest.mark.asyncio
async def test_failures_in_report_omit_status_key_when_not_an_http_error(tmp_path, monkeypatch):
    (tmp_path / "sources").mkdir()
    _write_source_file(tmp_path / "sources", "lever", [{"identifier": "boom"}])

    async def crawl(source, context):
        raise RuntimeError("unexpected")

    monkeypatch.setitem(runner_module.CRAWLER_BY_PROVIDER, "lever", _FakeCrawler(crawl))

    options = _options(tmp_path, providers="lever")
    await runner_module.run_crawler(options)

    report_data = json.loads(Path(options.report).read_text())
    failure = report_data["failures"][0]
    assert "status" not in failure
    assert failure["message"] == "unexpected"


def test_is_fresh_enough_false_for_none_and_unparseable():
    assert runner_module._is_fresh_enough(None, 0) is False
    assert runner_module._is_fresh_enough("not a date", 0) is False


def test_is_fresh_enough_true_for_recent_naive_datetime_treated_as_utc():
    import time

    now_ms = time.time() * 1000
    assert runner_module._is_fresh_enough("2099-01-01T00:00:00", now_ms) is True


def test_job_to_dict_includes_skill_tier_only_when_set():
    job = NormalizedJob(provider="lever", source_key="a", job_id="1", fetched_at="2026-01-01T00:00:00Z")
    assert "skill_tier" not in runner_module._job_to_dict(job)

    job_with_tier = NormalizedJob(
        provider="lever", source_key="a", job_id="1", fetched_at="2026-01-01T00:00:00Z", skill_tier="senior"
    )
    assert runner_module._job_to_dict(job_with_tier)["skill_tier"] == "senior"


@pytest.mark.asyncio
async def test_periodic_progress_events_are_written_and_cleaned_up(tmp_path, monkeypatch):
    (tmp_path / "sources").mkdir()
    _write_source_file(tmp_path / "sources", "lever", [{"identifier": "a"}])

    async def crawl(source, context):
        await asyncio.sleep(0.1)
        return []

    monkeypatch.setitem(runner_module.CRAWLER_BY_PROVIDER, "lever", _FakeCrawler(crawl))

    options = _options(tmp_path, providers="lever", progress_every_ms=10)
    await runner_module.run_crawler(options)

    payload = json.loads(Path(options.progress_file).read_text())
    assert payload["event"] == "done"


def test_interleave_work_items_round_robins_across_providers():
    items_by_provider = {
        "lever": [
            runner_module.WorkItem(provider="lever", source=SourceEntry(identifier="l1")),
            runner_module.WorkItem(provider="lever", source=SourceEntry(identifier="l2")),
        ],
        "ashby": [runner_module.WorkItem(provider="ashby", source=SourceEntry(identifier="a1"))],
    }
    result = runner_module._interleave_work_items(["lever", "ashby"], items_by_provider)
    assert [item.source.identifier for item in result] == ["l1", "a1", "l2"]


@pytest.mark.asyncio
async def test_per_provider_concurrency_cap_enforced(tmp_path, monkeypatch):
    (tmp_path / "sources").mkdir()
    _write_source_file(
        tmp_path / "sources",
        "workday",
        [{"tenant": f"t{i}", "shard": "wd1", "site": "External"} for i in range(6)],
    )

    active = {"n": 0}
    peak = {"n": 0}
    lock = asyncio.Lock()

    async def crawl(source, context):
        async with lock:
            active["n"] += 1
            peak["n"] = max(peak["n"], active["n"])
        await asyncio.sleep(0.05)
        async with lock:
            active["n"] -= 1
        return []

    monkeypatch.setitem(runner_module.CRAWLER_BY_PROVIDER, "workday", _FakeCrawler(crawl))

    options = _options(tmp_path, providers="workday", concurrency=10, provider_concurrency={"workday": 2})
    await runner_module.run_crawler(options)

    assert peak["n"] <= 2


@pytest.mark.asyncio
async def test_worker_steals_next_item_instead_of_waiting_on_static_partition(tmp_path, monkeypatch):
    (tmp_path / "sources").mkdir()
    _write_source_file(
        tmp_path / "sources",
        "lever",
        [{"identifier": "slow"}, {"identifier": "fast1"}, {"identifier": "fast2"}, {"identifier": "fast3"}],
    )

    durations = {"slow": 0.2, "fast1": 0.01, "fast2": 0.01, "fast3": 0.01}
    order = []

    async def crawl(source, context):
        await asyncio.sleep(durations[source.identifier])
        order.append(source.identifier)
        return []

    monkeypatch.setitem(runner_module.CRAWLER_BY_PROVIDER, "lever", _FakeCrawler(crawl))

    options = _options(tmp_path, providers="lever", concurrency=2)
    await runner_module.run_crawler(options)

    # A naive static 2-worker partition (worker A: [slow, fast1], worker B: [fast2, fast3]) would
    # leave fast1 stuck behind slow on the same worker, finishing last. Under the shared-cursor
    # work-stealing pattern, the idle worker claims fast1 immediately after slow is claimed, so it
    # finishes well before slow does.
    assert order.index("fast1") < order.index("slow")


@pytest.mark.asyncio
async def test_empty_source_list_does_not_wipe_existing_catalog(tmp_path):
    from catalog_store import CatalogStore

    (tmp_path / "sources").mkdir()
    (tmp_path / "state").mkdir()
    store = CatalogStore(str(tmp_path / "state" / "catalog.sqlite"))
    store.record_jobs(
        [NormalizedJob(provider="greenhouse", source_key="acme", job_id="1", fetched_at="x", title="T")],
        "previous_run",
    )
    store.close()

    with pytest.raises(RuntimeError, match="no sources"):
        await runner_module.run_crawler(_options(tmp_path))

    rows = (
        sqlite3.connect(str(tmp_path / "state" / "catalog.sqlite"))
        .execute("SELECT COUNT(*) FROM catalog_jobs")
        .fetchone()[0]
    )
    assert rows == 1
