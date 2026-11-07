"""Unit tests for the artist-name cleanup script."""

import sqlite3

from lytter.app import normalize_name
from lytter.fix_artist_names import find_dirty_artists

SEED = [
    ("Beach House (on Bad)", 1),
    ("Beach House (on Bad)", 2),
    ("Beach House", 3),
    ("Drongo [on Bad]", 4),
]


def _seed(conn):
    """Insert artists with keys computed exactly like production does."""
    for artist, ts in SEED:
        conn.execute(
            "INSERT INTO musiclibrary (artist, track, timestamp, artist_key, album_key, track_key)"
            " VALUES (?, 'x', ?, ?, '', '')",
            (artist, ts, normalize_name(artist, "artist")),
        )


def test_find_dirty_artists_reports_candidates(test_db):
    """Each dirty artist name: old, cleaned, play count, merges-with-clean-twin."""
    with sqlite3.connect(test_db) as conn:
        _seed(conn)
        assert find_dirty_artists(conn) == [
            ("Beach House (on Bad)", "Beach House", 2, True),
            ("Drongo [on Bad]", "Drongo", 1, False),
        ]
