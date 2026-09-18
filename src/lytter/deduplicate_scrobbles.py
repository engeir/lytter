"""
Deduplication script for near-duplicate scrobbles in the music database.

This script identifies and removes scrobbles that are near-duplicates (same artist+album+track
within a configurable time window). It keeps the first occurrence and removes subsequent ones.

Usage:
    uv run lytter-deduplicate    # Dry run (shows what would be deleted)
    uv run lytter-deduplicate --execute  # Actually delete duplicates
    uv run lytter-deduplicate --window 30  # Use 30-second window instead of 60
"""

import argparse
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Import from app module
from lytter.app import DUPLICATE_WINDOW_SECONDS

MAX_DISPLAY_DUPLICATES = 100


def get_db_path() -> Path:
    """Get the database path."""
    return Path("music.db")


def find_near_duplicates(
    conn: sqlite3.Connection, window_seconds: int = DUPLICATE_WINDOW_SECONDS
) -> list[tuple]:
    """
    Find near-duplicate scrobbles in the database.

    Parameters
    ----------
    conn : sqlite3.Connection
        SQLite database connection.
    window_seconds : int
        Time window in seconds for considering duplicates.

    Returns
    -------
    list[tuple]
        List of tuples (rowid_to_delete, artist, album, track, timestamp, duplicate_of_rowid).
    """
    cursor = conn.cursor()

    # Fetch all scrobbles ordered by artist_key, album_key, track_key, timestamp
    cursor.execute(
        """
        SELECT rowid, artist_key, album_key, track_key, timestamp, artist, album, track
        FROM musiclibrary
        ORDER BY artist_key, album_key, track_key, timestamp
    """
    )

    rows = cursor.fetchall()

    # Group by artist_key + album_key + track_key
    groups = defaultdict(list)
    for row in rows:
        rowid, artist_key, album_key, track_key, timestamp, artist, album, track = row
        key = (artist_key, album_key, track_key)
        groups[key].append((timestamp, rowid, artist, album, track))

    # Find duplicates to delete
    duplicates_to_delete = []

    for timestamps in groups.values():
        if len(timestamps) <= 1:
            continue

        # Sort by timestamp
        timestamps.sort()

        # Keep track of the first occurrence in each window
        # We'll keep the first occurrence and delete subsequent ones within the window
        keep_rowid = timestamps[0][1]
        keep_timestamp = timestamps[0][0]

        for i in range(1, len(timestamps)):
            curr_timestamp, curr_rowid, curr_artist, curr_album, curr_track = (
                timestamps[i]
            )

            # Check if this is within the window of the kept scrobble
            if curr_timestamp - keep_timestamp <= window_seconds:
                # This is a duplicate, mark for deletion
                duplicates_to_delete.append(
                    (
                        curr_rowid,
                        curr_artist,
                        curr_album,
                        curr_track,
                        curr_timestamp,
                        keep_rowid,
                    )
                )
            else:
                # This is outside the window, so it becomes the new reference
                keep_rowid = curr_rowid
                keep_timestamp = curr_timestamp

    return duplicates_to_delete


def deduplicate_database(
    dry_run: bool = True, window_seconds: int = DUPLICATE_WINDOW_SECONDS
) -> int:
    """
    Find and remove near-duplicate scrobbles.

    Parameters
    ----------
    dry_run : bool
        If True, only report what would be deleted without actually deleting.
    window_seconds : int
        Time window in seconds for considering duplicates.

    Returns
    -------
    int
        Number of duplicates that would be/were deleted.
    """
    db_path = get_db_path()

    if not db_path.exists():
        print(f"Error: Database file not found at {db_path}")
        return 0

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = OFF")

    try:
        duplicates = find_near_duplicates(conn, window_seconds)

        if not duplicates:
            print("No near-duplicates found.")
            return 0

        print(f"Found {len(duplicates)} near-duplicate scrobbles to remove.")

        if dry_run:
            print("\nDry run - the following scrobbles would be deleted:")
            print("-" * 80)
            for dup in duplicates[:MAX_DISPLAY_DUPLICATES]:
                rowid, artist, album, track, timestamp, keep_rowid = dup

                dt = datetime.fromtimestamp(timestamp)
                print(
                    f"  Row {rowid}: {artist} - {album} - {track} @ {dt} (keep row {keep_rowid})"
                )
            if len(duplicates) > MAX_DISPLAY_DUPLICATES:
                print(f"  ... and {len(duplicates) - MAX_DISPLAY_DUPLICATES} more")
            print("-" * 80)
            print(f"\nTotal: {len(duplicates)} duplicates would be deleted.")
            print("\nTo actually delete them, run with --execute flag.")
            return len(duplicates)

        # Actually delete the duplicates
        print("\nDeleting duplicates...")
        cursor = conn.cursor()

        # Sort by rowid in descending order to avoid issues with auto-increment
        duplicates.sort(key=lambda x: x[0], reverse=True)

        deleted_count = 0
        for dup in duplicates:
            rowid = dup[0]
            try:
                cursor.execute("DELETE FROM musiclibrary WHERE rowid = ?", (rowid,))
                deleted_count += 1
            except sqlite3.Error as e:
                print(f"  Error deleting row {rowid}: {e}")

        conn.commit()
        print(f"\nDeleted {deleted_count} near-duplicate scrobbles.")

        return deleted_count

    finally:
        conn.close()


def main() -> None:
    """Run the deduplication script."""
    parser = argparse.ArgumentParser(
        description="Remove near-duplicate scrobbles from the music database."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete duplicates (default is dry run)",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=DUPLICATE_WINDOW_SECONDS,
        help=f"Time window in seconds (default: {DUPLICATE_WINDOW_SECONDS})",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Alias for --execute",
    )

    args = parser.parse_args()

    dry_run = not (args.execute or args.yes)
    window = args.window

    print("Near-duplicate scrobble cleanup")
    print(f"  Window: {window} seconds")
    print(f"  Mode: {'DRY RUN' if dry_run else 'EXECUTE'}")
    print()

    count = deduplicate_database(dry_run=dry_run, window_seconds=window)

    if dry_run and count > 0:
        sys.exit(1)  # Exit with error code to indicate work needs to be done


if __name__ == "__main__":
    main()
