#!/usr/bin/env python3
"""Background service for automatic Last.fm database updates."""

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from lytter.app import GetScrobbles, init_db

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("lastfm_updater.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def update_database():
    """Perform incremental database update."""
    logger.info("Starting automatic database update")

    try:
        # Initialize database if needed
        init_db()

        # Perform incremental update
        downloader = GetScrobbles()
        new_scrobbles = downloader.get_scrobbles()

        if new_scrobbles > 0:
            logger.info(f"✅ Update completed: {new_scrobbles} new scrobbles added")
        else:
            logger.info("✅ Database is up to date")

    except Exception as e:
        logger.error(f"❌ Update failed: {e}")


def main():
    """Run the scheduler for background updates."""
    logger.info("🚀 Starting Last.fm background updater")
    logger.info("Schedule: Every hour")

    scheduler = BlockingScheduler()

    # Schedule updates every hour
    scheduler.add_job(
        update_database,
        CronTrigger(minute=5),  # Run at 5 minutes past each hour
        id="hourly_update",
        name="Hourly Last.fm Update",
        misfire_grace_time=300,  # Allow up to 5 minutes delay
    )

    # Run initial update
    logger.info("Running initial update...")
    update_database()

    try:
        logger.info("Scheduler started. Press Ctrl+C to stop.")
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")
    except Exception as e:
        logger.error(f"Scheduler error: {e}")


if __name__ == "__main__":
    main()
