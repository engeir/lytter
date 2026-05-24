"""Tests for helper functions in lytter.app."""

import sqlite3

import lytter.app as app_module


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
