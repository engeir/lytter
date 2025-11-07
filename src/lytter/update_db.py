#!/usr/bin/env python3
"""Command-line utility to update the Last.fm database."""

import argparse
import sys

from lytter.app import GetScrobbles, init_db


def main():
    """Update the Last.fm scrobbles database."""
    parser = argparse.ArgumentParser(description="Update Last.fm scrobbles database")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Perform a full update (downloads all scrobbles)",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=0,
        help="Limit number of pages to fetch (0 = no limit)",
    )
    parser.add_argument(
        "--thorough",
        action="store_true",
        help="Thorough incremental update (checks more pages, slower but more reliable)",
    )

    args = parser.parse_args()

    # Initialize database if it doesn't exist
    init_db()

    # Create downloader
    downloader = GetScrobbles()

    if args.full:
        print("🔄 Starting FULL database update...")
        print("⚠️  This will download your entire Last.fm history and may take a while!")
        confirm = input("Are you sure? (y/N): ")
        if confirm.lower() != "y":
            print("Cancelled.")
            sys.exit(0)
        downloader.get_scrobbles(full=True, pages=args.pages)
    elif args.thorough:
        print("🔄 Starting THOROUGH incremental update...")
        print("This will check more pages to ensure no gaps, but will be slower.")
        # For thorough mode, check more pages but still not full
        pages_to_check = (
            args.pages if args.pages > 0 else 20
        )  # Check 20 pages instead of 5
        downloader.get_scrobbles(pages=pages_to_check)
    else:
        print("🔄 Starting quick incremental database update...")
        downloader.get_scrobbles(pages=args.pages)

    print("✅ Database update completed!")


if __name__ == "__main__":
    main()
