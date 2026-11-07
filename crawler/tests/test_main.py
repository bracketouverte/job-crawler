import pytest

import main as main_module
from models import CrawlReport


def _fake_report() -> CrawlReport:
    return CrawlReport(
        started_at="2026-01-01T00:00:00Z",
        ended_at="2026-01-01T00:01:00Z",
        source_counts={},
        skipped_sources=0,
        skipped_by_provider={},
        providers={},
        total_jobs=3,
        failures=[],
    )


def _argv(tmp_path, progress_file=None):
    return [
        "main.py",
        "--sources",
        str(tmp_path / "sources"),
        "--out",
        str(tmp_path / "out" / "jobs.jsonl"),
        "--report",
        str(tmp_path / "out" / "report.json"),
        "--catalog-db",
        str(tmp_path / "state" / "catalog.sqlite"),
        "--progress-file",
        str(progress_file or (tmp_path / "state" / "progress.json")),
    ]


@pytest.mark.asyncio
async def test_lock_file_exists_during_crawl_and_removed_after_success(tmp_path, monkeypatch):
    lock_path = tmp_path / "state" / "crawler-active.lock"
    monkeypatch.setenv("CRAWLER_ACTIVE_LOCK_PATH", str(lock_path))
    seen_exists_during_crawl = {"v": False}

    async def fake_run_crawler(options):
        seen_exists_during_crawl["v"] = lock_path.exists()
        return _fake_report()

    monkeypatch.setattr(main_module, "run_crawler", fake_run_crawler)
    monkeypatch.setattr(main_module.post_crawl, "run", lambda *a, **k: 0)
    monkeypatch.setattr(main_module, "append_trend_entry", lambda *a, **k: None)
    monkeypatch.setattr("sys.argv", _argv(tmp_path))

    exit_code = await main_module.main()

    assert seen_exists_during_crawl["v"] is True
    assert not lock_path.exists()
    assert exit_code == 0


@pytest.mark.asyncio
async def test_crawl_exception_removes_lock_skips_post_crawl_returns_1(tmp_path, monkeypatch):
    lock_path = tmp_path / "state" / "crawler-active.lock"
    monkeypatch.setenv("CRAWLER_ACTIVE_LOCK_PATH", str(lock_path))

    async def fake_run_crawler(options):
        assert lock_path.exists()
        raise RuntimeError("boom")

    post_crawl_called = {"v": False}

    def fake_post_crawl_run(*_args, **_kwargs):
        post_crawl_called["v"] = True

    monkeypatch.setattr(main_module, "run_crawler", fake_run_crawler)
    monkeypatch.setattr(main_module.post_crawl, "run", fake_post_crawl_run)
    monkeypatch.setattr("sys.argv", _argv(tmp_path))

    exit_code = await main_module.main()

    assert not lock_path.exists()
    assert post_crawl_called["v"] is False
    assert exit_code == 1


@pytest.mark.asyncio
async def test_progress_file_removed_after_success(tmp_path, monkeypatch):
    progress_path = tmp_path / "state" / "progress.json"
    monkeypatch.setenv("CRAWLER_ACTIVE_LOCK_PATH", str(tmp_path / "state" / "lock"))

    async def fake_run_crawler(options):
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.write_text("{}")
        return _fake_report()

    monkeypatch.setattr(main_module, "run_crawler", fake_run_crawler)
    monkeypatch.setattr(main_module.post_crawl, "run", lambda *a, **k: 0)
    monkeypatch.setattr(main_module, "append_trend_entry", lambda *a, **k: None)
    monkeypatch.setattr("sys.argv", _argv(tmp_path, progress_path))

    await main_module.main()

    assert not progress_path.exists()


@pytest.mark.asyncio
async def test_progress_file_removed_after_failure(tmp_path, monkeypatch):
    progress_path = tmp_path / "state" / "progress.json"
    monkeypatch.setenv("CRAWLER_ACTIVE_LOCK_PATH", str(tmp_path / "state" / "lock"))

    async def fake_run_crawler(options):
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.write_text("{}")
        raise RuntimeError("boom")

    monkeypatch.setattr(main_module, "run_crawler", fake_run_crawler)
    monkeypatch.setattr("sys.argv", _argv(tmp_path, progress_path))

    exit_code = await main_module.main()

    assert not progress_path.exists()
    assert exit_code == 1


@pytest.mark.asyncio
async def test_post_crawl_failure_returns_1(tmp_path, monkeypatch):
    monkeypatch.setenv("CRAWLER_ACTIVE_LOCK_PATH", str(tmp_path / "state" / "lock"))

    async def fake_run_crawler(options):
        return _fake_report()

    def failing_post_crawl(report_path, exclude_path):
        raise RuntimeError("bad report")

    monkeypatch.setattr(main_module, "run_crawler", fake_run_crawler)
    monkeypatch.setattr(main_module.post_crawl, "run", failing_post_crawl)
    monkeypatch.setattr("sys.argv", _argv(tmp_path))

    exit_code = await main_module.main()

    assert exit_code == 1


@pytest.mark.asyncio
async def test_trend_log_failure_is_non_fatal(tmp_path, monkeypatch):
    monkeypatch.setenv("CRAWLER_ACTIVE_LOCK_PATH", str(tmp_path / "state" / "lock"))

    async def fake_run_crawler(options):
        return _fake_report()

    def failing_trend_log(db_path, state_dir):
        raise RuntimeError("no db yet")

    monkeypatch.setattr(main_module, "run_crawler", fake_run_crawler)
    monkeypatch.setattr(main_module.post_crawl, "run", lambda *a, **k: 0)
    monkeypatch.setattr(main_module, "append_trend_entry", failing_trend_log)
    monkeypatch.setattr("sys.argv", _argv(tmp_path))

    exit_code = await main_module.main()

    assert exit_code == 0


@pytest.mark.asyncio
async def test_success_prints_summary_matching_report_fields(tmp_path, monkeypatch, capsys):
    async def fake_run_crawler(options):
        return _fake_report()

    monkeypatch.setenv("CRAWLER_ACTIVE_LOCK_PATH", str(tmp_path / "state" / "lock"))
    monkeypatch.setattr(main_module, "run_crawler", fake_run_crawler)
    monkeypatch.setattr(main_module.post_crawl, "run", lambda *a, **k: 0)
    monkeypatch.setattr(main_module, "append_trend_entry", lambda *a, **k: None)
    monkeypatch.setattr("sys.argv", _argv(tmp_path))

    await main_module.main()

    import json

    out = capsys.readouterr().out
    summary = json.loads(out)
    assert summary["total_jobs"] == 3
    assert summary["failures"] == 0
    assert summary["started_at"] == "2026-01-01T00:00:00Z"
