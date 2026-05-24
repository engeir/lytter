"""Pytest configuration and shared fixtures for lytter tests."""

import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

import lytter.app as app_module
from lytter.app import app


@pytest.fixture()
def test_db(tmp_path, monkeypatch):
    """File-based SQLite DB in tmp_path with schema + sample data, DB_NAME monkeypatched."""
    db = tmp_path / "test.db"
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
                timestamp INTEGER UNIQUE NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE track_durations (
                artist TEXT NOT NULL,
                track TEXT NOT NULL,
                duration_ms INTEGER,
                fetched_at INTEGER NOT NULL,
                PRIMARY KEY (artist, track)
            )
        """)
        now = int(time.time())
        rows = [
            ("Radiohead", None, "OK Computer", None, "Paranoid Android", None, now - 120),
            ("Radiohead", None, "OK Computer", None, "Karma Police", None, now - 480),
            ("K.Flay", None, "Every Where Is Some Where", None, "Blood in the Cut", None, now - 720),
        ]
        conn.executemany(
            "INSERT INTO musiclibrary (artist, artist_mbid, album, album_mbid, track, track_mbid, timestamp) VALUES (?,?,?,?,?,?,?)",
            rows,
        )
        conn.execute(
            "INSERT INTO track_durations (artist, track, duration_ms, fetched_at) VALUES (?,?,?,?)",
            ("Radiohead", "Paranoid Android", 383000, now),
        )
    return db


@pytest.fixture()
def client(test_db):
    """FastAPI TestClient with monkeypatched DB."""
    return TestClient(app)
