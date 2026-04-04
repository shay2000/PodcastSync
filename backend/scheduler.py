"""APScheduler setup for periodic source polling."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

POLL_JOB_ID = "poll_sources"


def create_scheduler(interval_minutes: int, sync_func) -> AsyncIOScheduler:
    """Create and configure the scheduler. Does NOT start it — call .start() separately."""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        sync_func,
        trigger="interval",
        minutes=interval_minutes,
        id=POLL_JOB_ID,
        name="Poll YouTube sources",
        replace_existing=True,
    )
    logger.info("Scheduler configured: poll every %d minutes", interval_minutes)
    return scheduler


def reschedule_poll(scheduler: AsyncIOScheduler, interval_minutes: int) -> None:
    """Update the polling interval of a running scheduler."""
    scheduler.reschedule_job(POLL_JOB_ID, trigger="interval", minutes=interval_minutes)
    logger.info("Scheduler rescheduled: poll every %d minutes", interval_minutes)
