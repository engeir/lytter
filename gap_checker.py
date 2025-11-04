#!/usr/bin/env python3
"""Check for gaps in the scrobbles database and fill them."""

import os
import sqlite3
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("API_KEY")
USER_NAME = os.environ.get("USER_NAME")


def get_db_connection():
    """Get database connection."""
    return sqlite3.connect("music.db")


def find_timestamp_gaps(hours_back=24, gap_threshold=3600):
    """Find suspicious gaps in timestamps.

    Args:
        hours_back: How many hours back to check
        gap_threshold: Gap in seconds that's considered suspicious (default 1 hour)
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get timestamps from last N hours
    cutoff_time = int((datetime.now() - timedelta(hours=hours_back)).timestamp())

    cursor.execute(
        """
        SELECT timestamp FROM musiclibrary
        WHERE timestamp > ?
        ORDER BY timestamp DESC
    """,
        (cutoff_time,),
    )

    timestamps = [row[0] for row in cursor.fetchall()]
    conn.close()

    gaps = []
    for i in range(len(timestamps) - 1):
        gap = int(timestamps[i]) - int(timestamps[i + 1])
        if gap > gap_threshold:
            gaps.append(
                {
                    "newer_ts": timestamps[i],
                    "older_ts": timestamps[i + 1],
                    "gap_seconds": gap,
                    "newer_time": datetime.fromtimestamp(int(timestamps[i])),
                    "older_time": datetime.fromtimestamp(int(timestamps[i + 1])),
                }
            )

    return gaps


def fetch_scrobbles_in_range(from_timestamp, to_timestamp):
    """Fetch scrobbles from Last.fm API in a specific time range."""
e   url  "https://ws.audioscrobbler.com/2.0/?method=user.getrecenttracks&user={}&api_key={}&limit=200&from={}&to={}&page={}&format=json"

    all_scrobbles = []
    page = 1

    while True:
        try:
            request_url = url.format(
                USER_NAME, API_KEY, from_timestamp, to_timestamp, page
            )
            response = requests.get(request_url, timeout=30)
            response.raise_for_status()
            data = response.json()

            if "recenttracks" not in data or "track" not in data["recenttracks"]:
                break

            tracks = data["recenttracks"]["track"]
            if not tracks:
                break

            # If it's a single track, make it a list
            if isinstance(tracks, dict):
                tracks = [tracks]

            for track in tracks:
                # Skip now playing
                if "@attr" in track and track["@attr"].get("nowplaying") == "true":
                    continue

                if "date" in track:
                    all_scrobbles.append(
                        {
                            "artist": track["artist"]["#text"],
                            "artist_mbid": track["artist"]["mbid"],
                            "album": track["album"]["#text"],
                            "album_mbid": track["album"]["mbid"],
                            "track": track["name"],
                            "track_mbid": track["mbid"],
                            "timestamp": int(track["date"]["uts"]),
                        }
                    )

            # Check if we have more pages
            total_pages = int(data["recenttracks"]["@attr"]["totalPages"])
            if page >= total_pages:
                break

            page += 1

        except Exception as e:
            print(f"Error fetching page {page}: {e}")
            break

    return all_scrobbles


def fill_gaps(gaps, dry_run=True):
    """Fill identified gaps by fetching missing scrobbles."""
    if not gaps:
        print("No gaps found!")
        return 0

    conn = get_db_connection()
    cursor = conn.cursor()
    total_added = 0

    for gap in gaps:
        print(
            f"\n🔍 Checking gap: {gap['gap_seconds']}s between {gap['newer_time']} and {gap['older_time']}"
        )

        # Fetch scrobbles in this time range
        scrobbles = fetch_scrobbles_in_range(gap["older_ts"], gap["newer_ts"])
        print(f"Found {len(scrobbles)} scrobbles from API in this range")

        added_count = 0
        for scrobble in scrobbles:
            # Check if this scrobble already exists
            cursor.execute(
                "SELECT 1 FROM musiclibrary WHERE timestamp = ?",
                (scrobble["timestamp"],),
            )
            if not cursor.fetchone():
                if not dry_run:
                    try:
                        cursor.execute(
                            """
                            INSERT INTO musiclibrary
                            (artist, artist_mbid, album, album_mbid, track, track_mbid, timestamp)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                            (
                                scrobble["artist"],
                                scrobble["artist_mbid"],
                                scrobble["album"],
                                scrobble["album_mbid"],
                                scrobble["track"],
                                scrobble["track_mbid"],
                                scrobble["timestamp"],
                            ),
                        )
                        conn.commit()
                        added_count += 1
                    except sqlite3.IntegrityError:
                        pass  # Already exists
                else:
                    added_count += 1

        if dry_run:
            print(f"Would add {added_count} missing scrobbles")
        else:
            print(f"Added {added_count} missing scrobbles")
        total_added += added_count

    conn.close()
    return total_added


def main():
    """Main gap checking function."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Check for and fill gaps in scrobbles database"
    )
    parser.add_argument(
        "--hours", type=int, default=24, help="Hours back to check for gaps"
    )
    parser.add_argument(
        "--gap-threshold", type=int, default=3600, help="Gap threshold in seconds"
    )
    parser.add_argument(
        "--fix", action="store_true", help="Actually fix gaps (default is dry run)"
    )

    args = parser.parse_args()

    print(
        f"🔍 Checking for gaps in last {args.hours} hours (threshold: {args.gap_threshold}s)"
    )

    gaps = find_timestamp_gaps(args.hours, args.gap_threshold)

    if not gaps:
        print("✅ No suspicious gaps found!")
        return

    print(f"\n⚠️  Found {len(gaps)} suspicious gaps:")
    for i, gap in enumerate(gaps, 1):
        print(
            f"{i}. {gap['gap_seconds']}s gap between {gap['newer_time']} and {gap['older_time']}"
        )

    if args.fix:
        print("\n🔧 Filling gaps...")
        total_added = fill_gaps(gaps, dry_run=False)
        print(f"\n✅ Added {total_added} missing scrobbles")
    else:
        print("\n📋 Dry run - to actually fix gaps, use --fix")
        total_would_add = fill_gaps(gaps, dry_run=True)
        print(f"\n📊 Would add {total_would_add} missing scrobbles")


if __name__ == "__main__":
    main()
