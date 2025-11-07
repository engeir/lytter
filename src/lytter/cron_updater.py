#!/usr/bin/env python3
"""Simple cron-friendly updater for Last.fm database."""

import logging
import sys
from pathlib import Path

from lytter.app import GetScrobbles, init_db

# Setup logging
log_file = Path(__file__).parent / "lytter_updates.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler() if "--verbose" in sys.argv else logging.NullHandler(),
    ],
)
logger = logging.getLogger(__name__)


def main():
    """Run incremental update suitable for cron."""
    logger.info("Starting automatic database update")

    try:
        # Initialize database if needed
        init_db()

        # Perform incremental update
        downloader = GetScrobbles()
        new_scrobbles = downloader.get_scrobbles()

        if new_scrobbles > 0:
            logger.info(f"✅ Update completed: {new_scrobbles} new scrobbles added")
            print(f"Added {new_scrobbles} new scrobbles")
        else:
            logger.info("✅ Database is up to date")
            if "--verbose" in sys.argv:
                print("Database is up to date")

    except Exception as e:
        logger.error(f"❌ Update failed: {e}")
        print(f"Update failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
