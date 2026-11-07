"""Clean-up script for scrobbles whose artist carries a listening-unit suffix.

Some scrobble sources append the playback unit to the artist name, e.g.
"Beach House (on Bad)". This script finds such artist names and (with
--execute) renames them to the cleaned name.

Usage:
    uv run lytter-fix-artists            # dry run: list what would be fixed
    uv run lytter-fix-artists --execute  # actually apply the fixes
"""

import sqlite3

from lytter.app import clean_artist_name, normalize_name


def find_dirty_artists(conn: sqlite3.Connection) -> list[tuple]:
    """Find artists whose name carries a listening-unit artifact.

    Parameters
    ----------
    conn : sqlite3.Connection
        SQLite database connection.
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
