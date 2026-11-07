from datetime import datetime
from zoneinfo import ZoneInfo

import config
import main
import state


def _dt(year, month, day, hour):
    return datetime(year, month, day, hour, 0, 0, tzinfo=ZoneInfo(config.TZ))


def test_is_active_window_weekday_within_8_to_20():
    monday = _dt(2026, 1, 5, 14)  # Jan 5 2026 is a Monday
    assert main.is_active_window(monday) is True


def test_is_active_window_weekday_outside_range():
    monday_early = _dt(2026, 1, 5, 6)
    monday_late = _dt(2026, 1, 5, 22)
    assert main.is_active_window(monday_early) is False
    assert main.is_active_window(monday_late) is False


def test_is_active_window_saturday_only_specific_hours():
    saturday_8am = _dt(2026, 1, 3, 8)  # Jan 3 2026 is a Saturday
    saturday_noon = _dt(2026, 1, 3, 12)
    assert main.is_active_window(saturday_8am) is True
    assert main.is_active_window(saturday_noon) is False


def test_is_active_window_sunday_only_8am():
    sunday_8am = _dt(2026, 1, 4, 8)  # Jan 4 2026 is a Sunday
    sunday_9am = _dt(2026, 1, 4, 9)
    assert main.is_active_window(sunday_8am) is True
    assert main.is_active_window(sunday_9am) is False


def test_maybe_run_skips_when_debounced(monkeypatch):
    monkeypatch.setattr(state, "is_debounced", lambda: True)
    called = []
    monkeypatch.setattr(main, "run_crawler", lambda: called.append(True))
    main.maybe_run()
    assert called == []


def test_maybe_run_runs_when_not_debounced(monkeypatch):
    monkeypatch.setattr(state, "is_debounced", lambda: False)
    called = []
    monkeypatch.setattr(main, "run_crawler", lambda: called.append(True))
    main.maybe_run()
    assert called == [True]


def test_startup_immediate_run_fires_in_active_window_when_not_debounced(monkeypatch):
    monkeypatch.setattr(main, "is_active_window", lambda now: True)
    monkeypatch.setattr(state, "is_debounced", lambda: False)
    called = []
    monkeypatch.setattr(main, "run_crawler", lambda: called.append(True))
    main.startup_immediate_run()
    assert called == [True]


def test_startup_immediate_run_skips_outside_window(monkeypatch):
    monkeypatch.setattr(main, "is_active_window", lambda now: False)
    monkeypatch.setattr(state, "is_debounced", lambda: False)
    called = []
    monkeypatch.setattr(main, "run_crawler", lambda: called.append(True))
    main.startup_immediate_run()
    assert called == []


def test_startup_immediate_run_skips_when_debounced(monkeypatch):
    monkeypatch.setattr(main, "is_active_window", lambda now: True)
    monkeypatch.setattr(state, "is_debounced", lambda: True)
    called = []
    monkeypatch.setattr(main, "run_crawler", lambda: called.append(True))
    main.startup_immediate_run()
    assert called == []


def test_build_scheduler_registers_three_cron_jobs():
    scheduler = main.build_scheduler()
    jobs = scheduler.get_jobs()
    assert len(jobs) == 3
    assert all(job.func is main.maybe_run for job in jobs)


def test_main_runs_startup_check_then_starts_scheduler(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "setup_logging", lambda: calls.append("setup_logging"))
    monkeypatch.setattr(main, "startup_immediate_run", lambda: calls.append("startup_immediate_run"))

    # Use the real scheduler (with its real, not-yet-started Job objects) so
    # the per-job logging line in main() is exercised for real — a mocked
    # scheduler previously hid an AttributeError on job.next_run_time, which
    # only APScheduler populates after .start() actually runs.
    real_scheduler = main.build_scheduler()
    monkeypatch.setattr(real_scheduler, "start", lambda: calls.append("start"))
    monkeypatch.setattr(main, "build_scheduler", lambda: real_scheduler)

    main.main()
    assert calls == ["setup_logging", "startup_immediate_run", "start"]


def test_setup_logging_falls_back_to_stdout_when_log_path_unwritable(monkeypatch):
    monkeypatch.setattr(config, "LOG_PATH", "/no/such/dir/scheduler.log")
    main.setup_logging()  # must not raise
