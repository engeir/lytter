"""Tests for helper functions in lytter.app."""

import sqlite3
import time

import lytter.app as app_module
from lytter.app import backfill_keys, init_db, normalize_name


def test_get_dashboard_stats_counts(test_db):
    """Dashboard stats returns correct counts matching fixture data."""
    with sqlite3.connect(test_db) as conn:
        stats = app_module._get_dashboard_stats(conn)

    assert stats["total_scrobbles"] == 3  # noqa: PLR2004
    assert stats["unique_artists"] == 2  # noqa: PLR2004
    assert stats["unique_tracks"] == 3  # noqa: PLR2004
    assert stats["unique_albums"] == 2  # noqa: PLR2004


def test_get_dashboard_stats_listening_time(test_db):
    """Dashboard stats computes listening time only from tracks with known duration."""
    with sqlite3.connect(test_db) as conn:
        stats = app_module._get_dashboard_stats(conn)

    # Only Radiohead/Paranoid Android has a duration (383000ms, played 1x)
    assert stats["total_listening_time"] is not None
    assert stats["listening_time_known_tracks"] == 1
    assert stats["listening_time_total_tracks"] == 3  # noqa: PLR2004


def test_get_dashboard_stats_streaks(test_db):
    """Dashboard stats returns non-negative integer streaks."""
    with sqlite3.connect(test_db) as conn:
        stats = app_module._get_dashboard_stats(conn)

    assert isinstance(stats["current_streak"], int)
    assert isinstance(stats["longest_streak"], int)
    assert stats["current_streak"] >= 0
    assert stats["longest_streak"] >= 0


def test_relative_time_just_now():
    """Test relative time for very recent timestamp."""
    ts = int(time.time()) - 10
    assert app_module._relative_time(ts) == "just now"


def test_relative_time_minutes():
    """Test relative time for minutes ago."""
    ts = int(time.time()) - 300  # 5 minutes ago
    assert app_module._relative_time(ts) == "5m ago"


def test_relative_time_hours():
    """Test relative time for hours ago."""
    ts = int(time.time()) - 7200  # 2 hours ago
    assert app_module._relative_time(ts) == "2h ago"


def test_relative_time_days():
    """Test relative time for days ago."""
    ts = int(time.time()) - 172800  # 2 days ago
    assert app_module._relative_time(ts) == "2d ago"


def test_backfill_keys_populates_columns(tmp_path, monkeypatch):
    """backfill_keys() computes correct keys for existing rows with NULL keys."""
    db = tmp_path / "bk.db"
    monkeypatch.setattr(app_module, "DB_NAME", db)

    with sqlite3.connect(db) as conn:
        conn.execute("""
            CREATE TABLE musiclibrary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artist TEXT NOT NULL,
                artist_mbid TEXT,
                album TEXT,
                album_mbid TEXT,
                track TEXT NOT NULL,
                track_mbid TEXT,
                timestamp INTEGER UNIQUE NOT NULL,
                artist_key TEXT,
                album_key TEXT,
                track_key TEXT
            )
        """)
        conn.execute(
            "INSERT INTO musiclibrary (artist, album, track, timestamp) VALUES (?,?,?,?)",
            ("Angine de Poitrine", "Some Album", "La chanson", 1000),
        )
        conn.execute(
            "INSERT INTO musiclibrary (artist, album, track, timestamp) VALUES (?,?,?,?)",
            ("Angine de poitrine", "Some Album", "La Chanson", 2000),
        )
        backfill_keys(conn)

    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT artist, artist_key, track_key FROM musiclibrary ORDER BY timestamp"
        ).fetchall()

    assert rows[0][1] == normalize_name("Angine de Poitrine", "artist")
    assert rows[1][1] == normalize_name("Angine de poitrine", "artist")
    assert rows[0][1] == rows[1][1]  # same key
    assert rows[0][2] == rows[1][2]  # same track key


def test_init_db_adds_key_columns(tmp_path, monkeypatch):
    """init_db() adds key columns to an existing DB without dropping data."""
    db = tmp_path / "migrate.db"
    monkeypatch.setattr(app_module, "DB_NAME", db)

    # Create old-style table without key columns
    with sqlite3.connect(db) as conn:
        conn.execute("""
            CREATE TABLE musiclibrary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artist TEXT NOT NULL,
                artist_mbid TEXT,
                album TEXT,
                album_mbid TEXT,
                track TEXT NOT NULL,
                track_mbid TEXT,
                timestamp INTEGER UNIQUE NOT NULL
            )
        """)
        conn.execute(
            "INSERT INTO musiclibrary (artist, album, track, timestamp) VALUES (?,?,?,?)",
            ("Radiohead", "OK Computer", "Creep", 999),
        )

    init_db()  # should add columns and backfill

    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT artist, artist_key FROM musiclibrary WHERE timestamp = 999"
        ).fetchone()

    assert row[0] == "Radiohead"
    assert row[1] == "radiohead"


def test_dashboard_stats_deduplicates_by_key(tmp_path, monkeypatch):
    """unique_artists/tracks/albums count key groups, not raw string variants."""
    db = tmp_path / "dedup.db"
    monkeypatch.setattr(app_module, "DB_NAME", db)
    init_db()

    with sqlite3.connect(db) as conn:
        rows = [
            (
                "Angine de Poitrine",
                None,
                "Album",
                None,
                "Track",
                None,
                1000,
                normalize_name("Angine de Poitrine", "artist"),
                normalize_name("Album", "album"),
                normalize_name("Track", "track"),
            ),
            (
                "Angine de poitrine",
                None,
                "Album",
                None,
                "Track",
                None,
                2000,
                normalize_name("Angine de poitrine", "artist"),
                normalize_name("Album", "album"),
                normalize_name("Track", "track"),
            ),
        ]
        conn.executemany(
            "INSERT INTO musiclibrary "
            "(artist, artist_mbid, album, album_mbid, track, track_mbid, timestamp, "
            "artist_key, album_key, track_key) VALUES (?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        stats = app_module._get_dashboard_stats(conn)

    assert stats["unique_artists"] == 1  # two raw variants = one key group
    assert stats["unique_tracks"] == 1
    assert stats["unique_albums"] == 1
