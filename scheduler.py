"""
scheduler.py — APScheduler job definitions.

Jobs:
  fetch_job        — run_fetch_cycle()   every FETCH_INTERVAL_HOURS hours
  refresh_job      — refresh_items_cache() once daily at 02:00
  report_job       — run_analysis() + send_daily_report() at REPORT_TIME daily
  prune_job        — prune_old_snapshots() once weekly (Sunday 03:00)
"""

import logging
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

import config

log = logging.getLogger(__name__)


def _make_scheduler() -> BlockingScheduler:
    """Create and configure the APScheduler instance."""
    scheduler = BlockingScheduler(
        timezone="local",
        job_defaults={
            "coalesce": True,      # merge missed runs instead of queuing them
            "max_instances": 1,    # never run the same job concurrently
            "misfire_grace_time": 600,  # tolerate up to 10-min late start
        },
    )

    def _on_job_error(event):
        log.error(
            "Job '%s' raised an exception:\n%s",
            event.job_id,
            event.exception,
            exc_info=event.traceback,
        )

    def _on_job_done(event):
        log.debug("Job '%s' finished successfully.", event.job_id)

    scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)
    scheduler.add_listener(_on_job_done, EVENT_JOB_EXECUTED)

    return scheduler


def _fetch_job():
    """Wrapper so exceptions are caught and logged without crashing the scheduler."""
    from fetcher import run_fetch_cycle
    try:
        run_fetch_cycle()
    except Exception as exc:
        log.exception("Unhandled error in fetch_job: %s", exc)


def _refresh_job():
    from fetcher import refresh_items_cache
    try:
        count = refresh_items_cache()
        log.info("Items cache refreshed: %d items.", count)
    except Exception as exc:
        log.exception("Unhandled error in refresh_job: %s", exc)


def _report_job():
    from analyzer import run_analysis
    from notifier import send_daily_report
    try:
        report = run_analysis()
        send_daily_report(report)
    except Exception as exc:
        log.exception("Unhandled error in report_job: %s", exc)


def _prune_job():
    import database as db
    try:
        deleted = db.prune_old_snapshots(keep_days=120)
        log.info("Pruned %d old price snapshots.", deleted)
    except Exception as exc:
        log.exception("Unhandled error in prune_job: %s", exc)


def start(run_fetch_immediately: bool = True) -> None:
    """
    Start the blocking scheduler. This call never returns unless interrupted.
    """
    scheduler = _make_scheduler()

    # ── Fetch prices every N hours ─────────────────────────────────────────────
    scheduler.add_job(
        _fetch_job,
        trigger=IntervalTrigger(hours=config.FETCH_INTERVAL_HOURS),
        id="fetch_job",
        name="Fetch price data",
        next_run_time=datetime.now() if run_fetch_immediately else None,
    )

    # ── Refresh full item list once daily at 02:00 ─────────────────────────────
    scheduler.add_job(
        _refresh_job,
        trigger=CronTrigger(hour=2, minute=0),
        id="refresh_job",
        name="Refresh items cache",
    )

    # ── Daily report at configured time ───────────────────────────────────────
    report_hour, report_minute = _parse_time(config.REPORT_TIME)
    scheduler.add_job(
        _report_job,
        trigger=CronTrigger(hour=report_hour, minute=report_minute),
        id="report_job",
        name=f"Daily report ({config.REPORT_TIME})",
    )

    # ── Prune old data every Sunday at 03:00 ──────────────────────────────────
    scheduler.add_job(
        _prune_job,
        trigger=CronTrigger(day_of_week="sun", hour=3, minute=0),
        id="prune_job",
        name="Prune old snapshots",
    )

    log.info("Scheduler started. Jobs:")
    for job in scheduler.get_jobs():
        log.info("  %-20s  next run: %s", job.name, job.next_run_time)

    scheduler.start()


def _parse_time(time_str: str) -> tuple[int, int]:
    """Parse 'HH:MM' into (hour, minute). Defaults to (9, 0) on error."""
    try:
        parts = time_str.strip().split(":")
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        log.warning("Invalid REPORT_TIME '%s', defaulting to 09:00.", time_str)
        return 9, 0
