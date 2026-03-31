#!/usr/bin/env python3
"""Batch-fetch artist metadata (genre tags, bio, similar artists) for the library."""

import argparse
import sqlite3
import sys
import time

from lytter.app import (
    DB_NAME,
    fetch_and_cache_artist_genres,
    fetch_and_cache_artist_metadata,
    init_db,
)


def _get_artists(
    conn: sqlite3.Connection,
    *,
    retry_empty: bool,
    force: bool,
) -> list[str]:
    cursor = conn.cursor()
    if force:
        cursor.execute(
            "SELECT artist, COUNT(*) as plays FROM musiclibrary GROUP BY artist ORDER BY plays DESC"
        )
    elif retry_empty:
        # Never-attempted + previously returned empty tags
        cursor.execute("""
            SELECT m.artist, COUNT(*) as plays
            FROM musiclibrary m
            LEFT JOIN artist_genres ag ON ag.artist = m.artist
            WHERE ag.artist IS NULL OR ag.tags = '[]'
            GROUP BY m.artist
            ORDER BY plays DESC
        """)
    else:
        # Only artists with no entry in artist_genres at all
        cursor.execute("""
            SELECT m.artist, COUNT(*) as plays
            FROM musiclibrary m
            LEFT JOIN artist_genres ag ON ag.artist = m.artist
            WHERE ag.artist IS NULL
            GROUP BY m.artist
            ORDER BY plays DESC
        """)
    return [row[0] for row in cursor.fetchall()]


def main() -> None:
    """Batch-fetch genres and metadata for artists in the music library."""
    parser = argparse.ArgumentParser(
        description="Fetch and cache artist genres and metadata for the music library."
    )
    parser.add_argument(
        "--retry-empty",
        action="store_true",
        help="Also retry artists where a previous lookup returned no results.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch metadata for ALL artists, including those already cached.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        metavar="N",
        help="Stop after N artists (0 = no limit).",
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--genres-only",
        action="store_true",
        help="Only update genre tags; skip bio and similar artists.",
    )
    scope.add_argument(
        "--bio-only",
        action="store_true",
        help="Only update bio and similar artists; skip genre tags.",
    )
    args = parser.parse_args()

    init_db()

    with sqlite3.connect(DB_NAME) as conn:
        artists = _get_artists(conn, retry_empty=args.retry_empty, force=args.force)

    if args.limit > 0:
        artists = artists[: args.limit]

    total = len(artists)
    if total == 0:
        print("Nothing to fetch. Use --retry-empty or --force to fetch more.")
        sys.exit(0)

    mode = "all" if args.force else ("missing + empty" if args.retry_empty else "missing only")
    print(f"Fetching metadata for {total} artists ({mode})...")

    updated = 0
    failed = 0
    try:
        for i, artist in enumerate(artists, 1):
            print(f"[{i}/{total}] {artist}", flush=True)
            try:
                if not args.bio_only:
                    fetch_and_cache_artist_genres(artist)
                if not args.genres_only:
                    fetch_and_cache_artist_metadata(artist)
                updated += 1
            except Exception as exc:
                print(f"  ERROR: {exc}", flush=True)
                failed += 1
            if i < total:
                time.sleep(0.25)
    except KeyboardInterrupt:
        done = updated + failed
        print(f"\nInterrupted after {done}/{total} artists. Progress saved.")
        sys.exit(0)

    print(f"\nDone: {updated} updated, {failed} failed.")


if __name__ == "__main__":
    main()
