#!/usr/bin/env python3
"""Check database status and statistics."""

import datetime
import sqlite3

from lytter.app import get_db_connection

# Constants
SECONDS_PER_HOUR = 3600


def main():
    """Show database status."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get total scrobbles
        cursor.execute("SELECT COUNT(*) FROM musiclibrary")
        total_scrobbles = cursor.fetchone()[0]

        # Get latest scrobble
        cursor.execute("SELECT MAX(timestamp) FROM musiclibrary")
        latest_timestamp = cursor.fetchone()[0]

        # Get oldest scrobble
        cursor.execute("SELECT MIN(timestamp) FROM musiclibrary")
        oldest_timestamp = cursor.fetchone()[0]

        # Get unique artists
        cursor.execute("SELECT COUNT(DISTINCT artist) FROM musiclibrary")
        unique_artists = cursor.fetchone()[0]

        # Get unique tracks
        cursor.execute("SELECT COUNT(DISTINCT track) FROM musiclibrary")
        unique_tracks = cursor.fetchone()[0]

        conn.close()

        print("📊 Last.fm Database Status")
        print("=" * 40)
        print(f"Total scrobbles: {total_scrobbles:,}")
        print(f"Unique artists: {unique_artists:,}")
        print(f"Unique tracks: {unique_tracks:,}")

        if latest_timestamp:
            latest_date = datetime.datetime.fromtimestamp(int(latest_timestamp))
            print(f"Latest scrobble: {latest_date}")

            # Calculate how old the latest scrobble is
            time_diff = datetime.datetime.now() - latest_date

            if time_diff.days > 0:
                print(f"⚠️  Database is {time_diff.days} days behind")
            elif time_diff.seconds > SECONDS_PER_HOUR:
                hours = time_diff.seconds // SECONDS_PER_HOUR
                print(f"⚠️  Database is {hours} hours behind")
            else:
                print("✅ Database is up to date")

        if oldest_timestamp:
            oldest_date = datetime.datetime.fromtimestamp(int(oldest_timestamp))
            print(f"Oldest scrobble: {oldest_date}")

            # Calculate span
            if latest_timestamp and oldest_timestamp:
                span_days = (int(latest_timestamp) - int(oldest_timestamp)) // (
                    24 * 3600
                )
                print(f"Data span: {span_days:,} days")

        # Calculate average scrobbles per day
        if total_scrobbles and latest_timestamp and oldest_timestamp:
            span_days = max(
                1, (int(latest_timestamp) - int(oldest_timestamp)) // (24 * 3600)
            )
            avg_per_day = total_scrobbles / span_days
            print(f"Average: {avg_per_day:.1f} scrobbles/day")

    except sqlite3.OperationalError:
        print("❌ Database not found. Run 'uv run python update_db.py' to initialize.")
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    main()
