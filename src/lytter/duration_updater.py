#!/usr/bin/env python3
"""Batch-fetch track durations for all tracks in the library."""

import argparse
import sqlite3
import sys

from lytter.app import DB_NAME, fetch_and_cache_durations, init_db


def _get_tracks(
    conn: sqlite3.Connection,
    *,
    retry_failed: bool,
    force: bool,
) -> list[tuple[str, str, str | None]]:
    cursor = conn.cursor()
    if force:
        cursor.execute(
            "SELECT DISTINCT artist, track, MAX(track_mbid) FROM musiclibrary GROUP BY artist, track"
        )
    elif retry_failed:
        # Never-attempted + previously failed (NULL duration_ms)
        cursor.execute("""
            SELECT DISTINCT m.artist, m.track, MAX(m.track_mbid)
            FROM musiclibrary m
            LEFT JOIN track_durations td ON td.artist = m.artist AND td.track = m.track
            WHERE td.artist IS NULL OR td.duration_ms IS NULL
            GROUP BY m.artist, m.track
        """)
    else:
        # Only tracks with no entry in track_durations at all
        cursor.execute("""
            SELECT DISTINCT m.artist, m.track, MAX(m.track_mbid)
            FROM musiclibrary m
            LEFT JOIN track_durations td ON td.artist = m.artist AND td.track = m.track
            WHERE td.artist IS NULL
            GROUP BY m.artist, m.track
        """)
    return [(row[0], row[1], row[2] or None) for row in cursor.fetchall()]


def main() -> None:
    """Batch-fetch durations for library tracks missing duration data."""
    parser = argparse.ArgumentParser(
        description="Fetch and cache track durations for the music library."
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Also retry tracks where a previous lookup returned no result (NULL duration).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch durations for ALL tracks, including those already cached.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        metavar="N",
        help="Stop after N tracks (0 = no limit).",
    )
    args = parser.parse_args()

    init_db()

    with sqlite3.connect(DB_NAME) as conn:
        tracks = _get_tracks(conn, retry_failed=args.retry_failed, force=args.force)

    if args.limit > 0:
        tracks = tracks[: args.limit]

    total = len(tracks)
    if total == 0:
        print("Nothing to fetch. Use --retry-failed or --force to fetch more.")
        sys.exit(0)

    mode = "all tracks" if args.force else ("missing + failed" if args.retry_failed else "missing only")
    print(f"Fetching durations for {total} tracks ({mode})...")

    fetched = 0
    failed = 0
    try:
        for i, (artist, track, mbid) in enumerate(tracks, 1):
            print(f"[{i}/{total}] {artist} - {track}", flush=True)
            fetch_and_cache_durations([(artist, track, mbid)])
            # Check outcome
            with sqlite3.connect(DB_NAME) as conn:
                row = conn.execute(
                    "SELECT duration_ms FROM track_durations WHERE artist = ? AND track = ?",
                    (artist, track),
                ).fetchone()
            if row and row[0] is not None:
                fetched += 1
            else:
                failed += 1
    except KeyboardInterrupt:
        done = fetched + failed
        print(f"\nInterrupted after {done}/{total} tracks. Progress saved.")
        sys.exit(0)

    print(f"\nDone: {fetched} fetched, {failed} failed (no result found).")


if __name__ == "__main__":
    main()
