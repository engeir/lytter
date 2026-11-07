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


def test_timeline_default_returns_json(client):
    """Test that /charts/listening-timeline returns valid Plotly JSON."""
    response = client.get("/charts/listening-timeline")
    assert response.status_code == 200  # noqa: PLR2004
    data = response.json()
    assert "data" in data
    assert "layout" in data


def test_timeline_range_all_returns_json(client):
    """Test that /charts/listening-timeline?range=all returns valid Plotly JSON."""
    response = client.get("/charts/listening-timeline?range=all")
    assert response.status_code == 200  # noqa: PLR2004
    data = response.json()
    assert "data" in data
    assert "layout" in data


class _FakeTrack:
    artist = "Radiohead"
    title = "Paranoid Android"

    def get_album(self):
        """Return no album, like a track scrobbled without one."""
        return None


class _FakeNetwork:
    """Minimal pylast network that counts now-playing calls."""

    def __init__(self, calls: list[int]) -> None:
        self.calls = calls

    def get_user(self, _name):
        """Return a user whose now-playing track counts each call."""
        calls = self.calls

        class _User:
            def get_now_playing(self):
                calls.append(1)
                return _FakeTrack()

        return _User()


def test_index_caches_now_playing(client, monkeypatch):
    """A second page load within the cache window does not call Last.fm."""
    calls: list[int] = []
    monkeypatch.setattr(app_module, "network", _FakeNetwork(calls))
    app_module._now_playing_cache.clear()

    first = client.get("/")
    second = client.get("/")

    assert first.status_code == 200  # noqa: PLR2004
    assert "Paranoid Android" in first.text
    assert "Paranoid Android" in second.text
    assert len(calls) == 1


def test_responses_are_gzipped(client):
    """A page above the minimum size returns the gzip content encoding."""
    app_module._now_playing_cache.clear()
    response = client.get("/yearly", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200  # noqa: PLR2004
    assert response.headers.get("content-encoding") == "gzip"
