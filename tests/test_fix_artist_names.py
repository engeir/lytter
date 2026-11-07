"""Unit tests for the artist-name cleanup script."""

import sqlite3

from lytter.app import normalize_name
from lytter.fix_artist_names import clean_database, find_dirty_artists

DIRTY_ARTISTS = 2

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


def test_clean_database_dry_run_writes_nothing(test_db):
    """A dry run reports the renames and leaves the artists unchanged."""
    with sqlite3.connect(test_db) as conn:
        _seed(conn)
        assert clean_database(conn, dry_run=True) == DIRTY_ARTISTS
        assert conn.execute(
            "SELECT COUNT(*) FROM musiclibrary WHERE artist = 'Beach House (on Bad)'"
        ).fetchone() == (2,)
        assert conn.execute(
            "SELECT COUNT(*) FROM musiclibrary WHERE artist = 'Drongo [on Bad]'"
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT COUNT(*) FROM musiclibrary WHERE artist = 'Beach House'"
        ).fetchone() == (1,)


def test_clean_database_renames_artist_and_key(test_db):
    """Execute renames the artist text and recomputes artist_key."""
    with sqlite3.connect(test_db) as conn:
        _seed(conn)
        assert clean_database(conn, dry_run=False) == DIRTY_ARTISTS
        assert conn.execute(
            "SELECT COUNT(*) FROM musiclibrary WHERE artist = 'Beach House'"
        ).fetchone() == (3,)
        assert conn.execute(
            "SELECT COUNT(*) FROM musiclibrary WHERE artist_key = 'beach house'"
        ).fetchone() == (3,)
        assert conn.execute(
            "SELECT COUNT(*) FROM musiclibrary WHERE artist = 'Drongo'"
            " AND artist_key = 'drongo'"
        ).fetchone() == (1,)
