"""Tests for HTMX HTML fragment endpoints."""

import lytter.app as app_module  # noqa: F401  (ensures DB_NAME is patchable)


def test_recent_plays_returns_html(client):
    """Test that /html/recent-plays returns HTML with scrobble data."""
    response = client.get("/html/recent-plays")
    assert response.status_code == 200  # noqa: PLR2004
    assert "Paranoid Android" in response.text
    assert "Radiohead" in response.text
    assert "ago" in response.text


def test_recent_plays_is_ordered_newest_first(client):
    """Test that recent plays are ordered newest first."""
    response = client.get("/html/recent-plays")
    assert response.status_code == 200  # noqa: PLR2004
    # "Paranoid Android" (most recent, now-120s) before "Blood in the Cut" (now-720s)
    idx_paranoid = response.text.index("Paranoid Android")
    idx_blood = response.text.index("Blood in the Cut")
    assert idx_paranoid < idx_blood
