"""Crawl orchestration. Ported from crawler/src/runner.ts.

Concurrency model: a global pool of `worker_count` asyncio tasks share a
single mutable cursor index over an interleaved work-item list (a
work-stealing pattern -- a worker that finishes early immediately claims
the next unclaimed item, rather than each worker owning a pre-partitioned
slice). A per-provider asyncio.Semaphore (replacing the TS Limiter class)
enforces --provider-concurrency caps *inside* each worker's per-item task,
composing with the global pool.

Two optional/omittable NormalizedJob fields need special handling versus
plain dataclass serialization, matching JS's undefined-drops-the-key
behavior (Python's None does not, by default):
  - NormalizedJob.skill_tier is never set by any provider crawl function,
    so it must never appear as a key in jobs.jsonl output.
  - CrawlFailure.status is None when the error wasn't an HttpError, and
    must be omitted (not written as `null`) from both the report.json
    failures[] entries and the stderr failure log line.

The TS version's hand-rolled stream-backpressure-drain-event JsonlWriter
class (~50 lines, Node-stream-specific) is intentionally not ported --
an asyncio.Lock-guarded plain file handle is sufficient here, per the
migration plan's explicitly approved simplification.
"""

import asyncio
import contextlib
import json
import math
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
from dateutil import parser as date_parser

from catalog_store import CatalogStore
from config import CliOptions
from dead_slugs import load_dead_slugs, mark_dead
from exclusions import is_excluded, load_excluded_sources
from http_client import HttpClient, HttpError
from models import (
    PROVIDERS,
    CrawlContext,
    CrawlFailure,
    CrawlReport,
    NormalizedJob,
    Provider,
    ProviderStats,
    SourceEntry,
)
from providers import CRAWLER_BY_PROVIDER
from source_loader import load_source_file, parse_provider_list, source_key

HTML_SCRAPING_PROVIDERS = {"bamboohr", "workday", "teamtailor", "workable", "icims"}
_UNLIMITED_CONCURRENCY = 2**31


@dataclass
class WorkItem:
    provider: Provider
    source: SourceEntry
    url_template: str | None = None
    jobid_template: str | None = None


async def run_crawler(options: CliOptions) -> CrawlReport:
    started_at = _now_iso()
    selected_providers = parse_provider_list(options.providers)
    stats = _init_stats()
    failures: list[CrawlFailure] = []
    excluded_sources = load_excluded_sources(options.exclude_sources)
    state_dir = str(Path(options.catalog_db).parent)
    dead_slugs = {p: load_dead_slugs(state_dir, p) for p in selected_providers}

    items_by_provider: dict[Provider, list[WorkItem]] = {}
    for provider in selected_providers:
        source_file = load_source_file(options.sources, provider)
        companies = (
            source_file.companies if options.sample is None else source_file.companies[: options.sample]
        )
        stats[provider].sources = len(companies)
        provider_items: list[WorkItem] = []
        for source in companies:
            key = source_key(source)
            if is_excluded(excluded_sources, provider, key):
                stats[provider].skipped += 1
                continue
            if key in dead_slugs[provider]:
                stats[provider].skipped += 1
                continue
            provider_items.append(
                WorkItem(
                    provider=provider,
                    source=source,
                    url_template=source_file.url_template,
                    jobid_template=source_file.jobid_template,
                )
            )
        items_by_provider[provider] = provider_items

    items = _interleave_work_items(selected_providers, items_by_provider)

    Path(options.out).parent.mkdir(parents=True, exist_ok=True)
    Path(options.report).parent.mkdir(parents=True, exist_ok=True)

    catalog_store = CatalogStore(options.catalog_db)
    seen_jobs: set[str] = set()
    min_updated_at_ms = (
        None if options.max_age_hours is None else time.time() * 1000 - options.max_age_hours * 60 * 60 * 1000
    )
    provider_semaphores = {
        p: asyncio.Semaphore(options.provider_concurrency.get(p, _UNLIMITED_CONCURRENCY)) for p in PROVIDERS
    }

    cursor_lock = asyncio.Lock()
    cursor_state = {"cursor": 0, "completed": 0}

    async def claim_next() -> WorkItem | None:
        async with cursor_lock:
            idx = cursor_state["cursor"]
            if idx >= len(items):
                return None
            cursor_state["cursor"] += 1
            return items[idx]

    started_ms = time.time() * 1000

    def log_progress(event: str) -> None:
        _emit_progress(
            event,
            started_ms,
            cursor_state["completed"],
            len(items),
            stats,
            len(failures),
            options.progress_file,
        )

    async def progress_loop() -> None:
        while True:
            await asyncio.sleep(options.progress_every_ms / 1000)
            log_progress("progress")

    worker_count = min(max(options.concurrency, 1), len(items) or 1)

    async with httpx.AsyncClient() as client:
        http = HttpClient(client, timeout_s=options.timeout_ms / 1000, retries=options.retries)
        http_with_jitter = HttpClient(
            client, timeout_s=options.timeout_ms / 1000, retries=options.retries, jitter_ms=(300, 1200)
        )
        jsonl_writer = _JsonlWriter(options.out)

        async def worker() -> None:
            while True:
                item = await claim_next()
                if item is None:
                    return

                key = source_key(item.source)
                crawler = CRAWLER_BY_PROVIDER.get(item.provider)
                if crawler is None:
                    no_crawler_error = Exception(f"No crawler for provider {item.provider}")
                    _record_failure(failures, stats[item.provider], item.provider, key, no_crawler_error)
                    cursor_state["completed"] += 1
                    continue

                try:
                    async with provider_semaphores[item.provider]:
                        context = CrawlContext(
                            http=http_with_jitter if item.provider in HTML_SCRAPING_PROVIDERS else http,
                            fetched_at=_now_iso(),
                            max_jobs_per_source=options.max_jobs_per_source,
                            url_template=item.url_template,
                            jobid_template=item.jobid_template,
                        )
                        jobs = await crawler.crawl(item.source, context)

                    catalog_store.record_jobs(jobs, started_at)

                    emitted = 0
                    for job in jobs:
                        if min_updated_at_ms is not None and not _is_fresh_enough(
                            job.posted_at or job.updated_at, min_updated_at_ms
                        ):
                            continue
                        dedupe_key = f"{job.provider}:{job.source_key}:{job.job_id}"
                        if dedupe_key in seen_jobs:
                            continue
                        seen_jobs.add(dedupe_key)
                        await jsonl_writer.write(job)
                        emitted += 1

                    stats[item.provider].succeeded += 1
                    stats[item.provider].jobs += emitted
                except Exception as error:  # noqa: BLE001 -- isolates one source's failure from the run
                    _record_failure(failures, stats[item.provider], item.provider, key, error)
                    if isinstance(error, HttpError) and error.status is not None:
                        mark_dead(state_dir, item.provider, key, error.status)
                finally:
                    cursor_state["completed"] += 1

        log_progress("start")
        progress_task = asyncio.create_task(progress_loop()) if options.progress_every_ms > 0 else None

        try:
            if not items:
                # finalize_run deletes every row from other runs; an empty run would wipe the catalog.
                raise RuntimeError("no sources loaded; refusing to finalize the run and delete the catalog")
            await asyncio.gather(*(worker() for _ in range(worker_count)))
            catalog_store.finalize_run(started_at)
        finally:
            if progress_task is not None:
                progress_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await progress_task
            await jsonl_writer.close()
            catalog_store.close()

    ended_at = _now_iso()
    report = CrawlReport(
        started_at=started_at,
        ended_at=ended_at,
        source_counts={p: stats[p].sources for p in PROVIDERS},
        skipped_sources=sum(stats[p].skipped for p in PROVIDERS),
        skipped_by_provider={p: stats[p].skipped for p in PROVIDERS},
        providers=stats,
        total_jobs=sum(stats[p].jobs for p in PROVIDERS),
        failures=failures,
    )

    Path(options.report).write_text(json.dumps(_report_to_dict(report), indent=2) + "\n", encoding="utf-8")
    log_progress("done")

    for provider in selected_providers:
        dead = dead_slugs[provider]
        if dead:
            print(
                json.dumps(
                    {
                        "event": "dead_slugs",
                        "provider": provider,
                        "skipped": len(dead),
                        "ttl_days": "3–10 (random per slug)",
                    }
                )
            )

    return report


def _init_stats() -> dict[Provider, ProviderStats]:
    return {p: ProviderStats() for p in PROVIDERS}


def _record_failure(
    failures: list[CrawlFailure], stats: ProviderStats, provider: Provider, key: str, error: Exception
) -> None:
    message = str(error)
    status = error.status if isinstance(error, HttpError) else None
    log_payload = {"event": "failure", "provider": provider, "source_key": key}
    if status is not None:
        log_payload["status"] = status
    log_payload["message"] = message
    print(json.dumps(log_payload), file=sys.stderr)
    stats.failed += 1
    failures.append(CrawlFailure(provider=provider, source_key=key, message=message, status=status))


def _report_to_dict(report: CrawlReport) -> dict:
    return {
        "started_at": report.started_at,
        "ended_at": report.ended_at,
        "source_counts": report.source_counts,
        "skipped_sources": report.skipped_sources,
        "skipped_by_provider": report.skipped_by_provider,
        "providers": {p: asdict(s) for p, s in report.providers.items()},
        "total_jobs": report.total_jobs,
        "failures": [_failure_to_dict(f) for f in report.failures],
    }


def _failure_to_dict(f: CrawlFailure) -> dict:
    d: dict = {"provider": f.provider, "source_key": f.source_key}
    if f.status is not None:
        d["status"] = f.status
    d["message"] = f.message
    return d


def _job_to_dict(job: NormalizedJob) -> dict:
    d = {
        "provider": job.provider,
        "source_key": job.source_key,
        "job_id": job.job_id,
        "title": job.title,
        "location": job.location,
        "employment_type": job.employment_type,
        "compensation": job.compensation,
        "department": job.department,
        "office": job.office,
        "language": job.language,
        "updated_at": job.updated_at,
        "posted_at": job.posted_at,
        "job_url": job.job_url,
        "fetched_at": job.fetched_at,
    }
    if job.skill_tier is not None:
        d["skill_tier"] = job.skill_tier
    return d


def _is_fresh_enough(updated_at: str | None, min_updated_at_ms: float) -> bool:
    if updated_at is None:
        return False
    try:
        dt = date_parser.parse(updated_at)
    except (ValueError, OverflowError):
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp() * 1000 >= min_updated_at_ms


def _interleave_work_items(
    selected_providers: list[Provider], items_by_provider: dict[Provider, list[WorkItem]]
) -> list[WorkItem]:
    queues = [{"items": items_by_provider.get(p, []), "index": 0} for p in selected_providers]
    items: list[WorkItem] = []

    while True:
        added_any = False
        for queue in queues:
            if queue["index"] < len(queue["items"]):
                items.append(queue["items"][queue["index"]])
                queue["index"] += 1
                added_any = True
        if not added_any:
            return items


def _emit_progress(
    event: str,
    started_ms: float,
    completed: int,
    total: int,
    stats: dict[Provider, ProviderStats],
    failure_count: int,
    progress_file: str | None,
) -> None:
    elapsed_seconds = _js_round((time.time() * 1000 - started_ms) / 1000)
    percent = 100 if total == 0 else _js_round((completed / total) * 100)
    jobs = 0
    succeeded = 0
    failed = 0
    by_provider = {}
    for provider in PROVIDERS:
        s = stats[provider]
        jobs += s.jobs
        succeeded += s.succeeded
        failed += s.failed
        by_provider[provider] = {
            "done": s.succeeded + s.failed,
            "total": s.sources,
            "skipped": s.skipped,
            "jobs": s.jobs,
            "failed": s.failed,
        }

    payload = {
        "event": event,
        "elapsed_seconds": elapsed_seconds,
        "completed_sources": completed,
        "total_sources": total,
        "percent": percent,
        "succeeded_sources": succeeded,
        "failed_sources": failed,
        "total_jobs": jobs,
        "failures_recorded": failure_count,
        "by_provider": by_provider,
    }

    print(json.dumps(payload))

    if progress_file:
        try:
            Path(progress_file).write_text(json.dumps(payload) + "\n", encoding="utf-8")
        except OSError:
            pass


def _js_round(x: float) -> int:
    return math.floor(x + 0.5)


def _now_iso() -> str:
    dt = datetime.now(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class _JsonlWriter:
    def __init__(self, path: str):
        self._file = open(path, "w", encoding="utf-8")  # noqa: SIM115 -- lifetime matches the writer object
        self._lock = asyncio.Lock()

    async def write(self, job: NormalizedJob) -> None:
        line = json.dumps(_job_to_dict(job)) + "\n"
        async with self._lock:
            self._file.write(line)

    async def close(self) -> None:
        async with self._lock:
            self._file.close()
