import logging
import logging.handlers
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import config
import state
from crawler import run_crawler

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        handlers.append(
            logging.handlers.RotatingFileHandler(config.LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3)
        )
    except OSError:
        # Log dir not writable (e.g. local dev outside the container) —
        # stdout logging alone is fine.
        pass
    logging.basicConfig(level=logging.INFO, format="[scheduler] %(levelname)s %(message)s", handlers=handlers)


def maybe_run() -> None:
    if state.is_debounced():
        logger.info(
            "Skipping run: last run was within the %s-minute debounce window", config.DEBOUNCE_MINUTES
        )
        return
    run_crawler()


def is_active_window(now: datetime) -> bool:
    dow = now.isoweekday()  # 1=Mon ... 6=Sat, 7=Sun
    if 1 <= dow <= 5:
        return 8 <= now.hour <= 20
    if dow == 6:
        return now.hour in config.SATURDAY_HOURS
    return now.hour in config.SUNDAY_HOURS


def startup_immediate_run() -> None:
    now = datetime.now(ZoneInfo(config.TZ))
    if is_active_window(now) and not state.is_debounced():
        logger.info("Startup: within active window and not debounced — running now")
        run_crawler()
    else:
        logger.info(
            "Startup: skipping immediate run (active_window=%s debounced=%s)",
            is_active_window(now),
            state.is_debounced(),
        )


def build_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone=config.TZ)
    weekday_trigger = CronTrigger(
        day_of_week="mon-fri", hour="8,10,12,14,16,18,20", minute=0, timezone=config.TZ
    )
    scheduler.add_job(maybe_run, weekday_trigger)
    scheduler.add_job(maybe_run, CronTrigger(day_of_week="sat", hour="8,14", minute=0, timezone=config.TZ))
    scheduler.add_job(maybe_run, CronTrigger(day_of_week="sun", hour="8", minute=0, timezone=config.TZ))
    return scheduler


def main() -> None:
    setup_logging()
    startup_immediate_run()

    scheduler = build_scheduler()
    for job in scheduler.get_jobs():
        logger.info("Registered job %s — trigger %s", job.id, job.trigger)

    scheduler.start()


if __name__ == "__main__":
    main()
