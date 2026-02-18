"""APScheduler-based scheduled runs. All scrapers run once per day (configurable cron)."""
from __future__ import annotations

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from hunter.config import get_config
from hunter.logging_config import setup_logging
from hunter.run import run_all


def start_scheduler() -> None:
    cfg = get_config()
    setup_logging(cfg)
    sched_cfg = cfg.get("scheduler", {})
    if not sched_cfg.get("enabled", True):
        logger.info("Scheduler disabled in config")
        return
    cron = sched_cfg.get("cron", "0 8 * * *")
    tz = sched_cfg.get("timezone", "Europe/Warsaw")
    scheduler = BlockingScheduler(timezone=tz)
    scheduler.add_job(run_all, CronTrigger.from_crontab(cron, timezone=tz))
    logger.info("Scheduler started: cron={} timezone={}", cron, tz)
    scheduler.start()


if __name__ == "__main__":
    start_scheduler()
