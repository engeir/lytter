"""Clean-up script for scrobbles whose artist carries a listening-unit suffix.

Some scrobble sources append the playback unit to the artist name, e.g.
"Beach House (on Bad)". This script finds such artist names and (with
--execute) renames them to the cleaned name.

Usage:
    uv run lytter-fix-artists            # dry run: list what would be fixed
    uv run lytter-fix-artists --execute  # actually apply the fixes
"""

import argparse
import sqlite3
from pathlib import Path

from lytter.app import DB_NAME, clean_artist_name, normalize_name

MAX_DISPLAY = 100


def find_dirty_artists(conn: sqlite3.Connection) -> list[tuple]:
    """Find artists whose name carries a listening-unit artifact.

    Parameters
    ----------
    conn : sqlite3.Connection
        SQLite database connection.

    Returns
    -------
    list[tuple]
        (old name, cleaned name, scrobble count, cleaned name already exists).
    """
    cursor = conn.execute(
        """
        SELECT artist, COUNT(*)
        FROM musiclibrary
        GROUP BY artist
        ORDER BY artist
        """
    )

    candidates = []
    for artist, count in cursor.fetchall():
        cleaned = clean_artist_name(artist)
        if cleaned == artist:
            continue
        twin = conn.execute(
            "SELECT 1 FROM musiclibrary WHERE artist_key = ? LIMIT 1",
            (normalize_name(cleaned, "artist"),),
        ).fetchone()
        candidates.append((artist, cleaned, count, twin is not None))

    return candidates


def clean_database(conn: sqlite3.Connection, dry_run: bool = True) -> int:
    """Rename artists that carry a listening-unit suffix.

    Parameters
    ----------
    conn : sqlite3.Connection
        SQLite database connection.
    dry_run : bool
        If True, only report the renames without writing them.

    Returns
    -------
    int
        Number of artist names that would be/were renamed.
    """
    candidates = find_dirty_artists(conn)
    if not candidates:
        print("No artist names with listening-unit suffixes found.")
        return 0

    print(f"Found {len(candidates)} artist names to clean:")
    print("-" * 80)
    for old, new, count, twin in candidates[:MAX_DISPLAY]:
        note = " (merges with existing name)" if twin else ""
        print(f"  {old} -> {new}  [{count} plays]{note}")
    if len(candidates) > MAX_DISPLAY:
        print(f"  ... and {len(candidates) - MAX_DISPLAY} more")
    print("-" * 80)

    if dry_run:
        print(f"\nTotal: {len(candidates)} artist names would be renamed.")
        print("\nTo actually rename them, run with --execute flag.")
        return len(candidates)

    print("\nRenaming...")
    for old, new, _count, _twin in candidates:
        conn.execute(
            "UPDATE musiclibrary SET artist = ?, artist_key = ? WHERE artist = ?",
            (new, normalize_name(new, "artist"), old),
        )
    conn.commit()
    print(f"\nRenamed {len(candidates)} artist names.")
    return len(candidates)


def main() -> None:
    """Run the artist-name cleanup script."""
    parser = argparse.ArgumentParser(
        description="Rename artists that carry a listening-unit suffix."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually rename artists (default is dry run)",
    )
    args = parser.parse_args()

    db_path = Path(DB_NAME)
    if not db_path.exists():
        print(f"Error: Database file not found at {db_path}")
        return

    print("Artist name cleanup")
    print(f"  Mode: {'DRY RUN' if not args.execute else 'EXECUTE'}")
    print()

    with sqlite3.connect(db_path) as conn:
        clean_database(conn, dry_run=not args.execute)


if __name__ == "__main__":
    main()
