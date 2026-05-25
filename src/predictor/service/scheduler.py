"""
scheduler.py — APScheduler job definitions.

Jobs:
  fetch_job        — run_fetch_cycle()        every FETCH_INTERVAL_HOURS hours
  refresh_job      — refresh_items_cache()    daily at 02:00
  report_job       — run_analysis() + send()  at REPORT_TIME daily
  relic_job        — refresh_relic_cache()    every Monday at 00:30
  prune_job        — prune_old_snapshots()    every Sunday at 03:00
  retrain_job      — retrain SVM model        every Sunday at 03:30
"""

import logging
from datetime import datetime

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from predictor.core import config

log = logging.getLogger(__name__)


def _make_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 600,
        },
    )

    def _on_error(event):
        log.error("Job '%s' failed:\n%s", event.job_id, event.exception, exc_info=event.traceback)

    def _on_done(event):
        log.debug("Job '%s' finished.", event.job_id)

    scheduler.add_listener(_on_error, EVENT_JOB_ERROR)
    scheduler.add_listener(_on_done, EVENT_JOB_EXECUTED)
    return scheduler


# ─── Job Wrappers ─────────────────────────────────────────────────────────────

def _fetch_job():
    from predictor.market.fetcher import run_fetch_cycle
    try:
        run_fetch_cycle()
    except Exception as exc:
        log.exception("fetch_job error: %s", exc)


def _refresh_job():
    from predictor.market.fetcher import refresh_items_cache
    try:
        count = refresh_items_cache()
        log.info("Items cache refreshed: %d items.", count)
    except Exception as exc:
        log.exception("refresh_job error: %s", exc)


def _report_job():
    from predictor.market.analyzer import run_analysis
    from predictor.service.notifier import send_daily_report
    try:
        report = run_analysis()
        send_daily_report(report)
    except Exception as exc:
        log.exception("report_job error: %s", exc)


def _relic_job():
    """Refresh relic drop tables weekly so we stay current after hotfixes."""
    from predictor.relics.relic_scraper import refresh_relic_cache
    try:
        count = refresh_relic_cache()
        log.info("Relic cache refreshed: %d relics.", count)
    except Exception as exc:
        log.exception("relic_job error: %s", exc)


def _prune_job():
    from predictor.core import database as db
    try:
        removed = db.prune_old_snapshots(keep_days=90)
        log.info("Pruned %d old price rows.", removed)
    except Exception as exc:
        log.exception("prune_job error: %s", exc)


def _retrain_job():
    """Re-train the SVM model weekly with accumulated data."""
    from predictor.market.analyzer import retrain
    try:
        ok = retrain()
        log.info("Model retrain: %s", "success" if ok else "insufficient data")
    except Exception as exc:
        log.exception("retrain_job error: %s", exc)


# ─── Start ────────────────────────────────────────────────────────────────────

def start(run_fetch_immediately: bool = True) -> None:
    """Start the blocking scheduler. Never returns unless interrupted."""
    scheduler = _make_scheduler()

    # Price data every N hours
    scheduler.add_job(
        _fetch_job,
        trigger=IntervalTrigger(hours=config.FETCH_INTERVAL_HOURS),
        id="fetch_job", name="Fetch prices",
        next_run_time=datetime.now() if run_fetch_immediately else None,
    )

    # Full item list refresh daily at 02:00
    scheduler.add_job(
        _refresh_job,
        trigger=CronTrigger(hour=2, minute=0),
        id="refresh_job", name="Refresh item list",
    )

    # Daily report
    h, m = _parse_time(config.REPORT_TIME)
    scheduler.add_job(
        _report_job,
        trigger=CronTrigger(hour=h, minute=m),
        id="report_job", name=f"Daily report ({config.REPORT_TIME})",
    )

    # Relic drop table refresh — every Monday at 00:30
    scheduler.add_job(
        _relic_job,
        trigger=CronTrigger(day_of_week="mon", hour=0, minute=30),
        id="relic_job", name="Refresh relic cache",
    )

    # Prune old data — every Sunday at 03:00
    scheduler.add_job(
        _prune_job,
        trigger=CronTrigger(day_of_week="sun", hour=3, minute=0),
        id="prune_job", name="Prune old snapshots",
    )

    # Retrain SVM — every Sunday at 03:30
    scheduler.add_job(
        _retrain_job,
        trigger=CronTrigger(day_of_week="sun", hour=3, minute=30),
        id="retrain_job", name="Retrain SVM model",
    )

    log.info("Scheduler started. Running in background...")
    scheduler.start()


def _parse_time(time_str: str) -> tuple[int, int]:
    try:
        h, m = time_str.strip().split(":")
        return int(h), int(m)
    except (ValueError, AttributeError):
        log.warning("Invalid REPORT_TIME '%s', defaulting to 09:00.", time_str)
        return 9, 0
