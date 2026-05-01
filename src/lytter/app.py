"""Simple FastAPI application for Last.fm stats."""

import datetime
import json
import os
import re
import sqlite3
import time as _time
import unicodedata
from collections import Counter, OrderedDict
from pathlib import Path
from urllib.parse import quote

import pylast
import requests
import uvicorn
from dotenv import load_dotenv
from rapidfuzz import fuzz, process

try:
    import lyricsgenius as _lyricsgenius
except ImportError:
    _lyricsgenius = None

try:
    import pandas as pd
    import plotly.express as px
    import plotly.graph_objects as go
    from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
except ImportError as e:
    print(f"Import error: {e}")
    print("Please install dependencies with: uv sync")

load_dotenv()

# Get package directory for templates and static files
_PKG_DIR = Path(__file__).parent
DB_NAME = Path("music.db")

# Configuration
API_KEY = os.environ.get("API_KEY", "")
API_SECRET = os.environ.get("API_SECRET", "")
USER_NAME = os.environ.get("USER_NAME", "")
PASSWORD = os.environ.get("PASSWORD", "")
PASSWORD_HASH = pylast.md5(PASSWORD) if PASSWORD else ""
UPDATE_PASSWORD = os.environ.get("UPDATE_PASSWORD")

# pylast network (will fail at runtime if env vars not set)
network = pylast.LastFMNetwork(
    api_key=API_KEY,
    api_secret=API_SECRET,
    username=USER_NAME,
    password_hash=PASSWORD_HASH,
)

app = FastAPI(
    title="Last.fm Stats", description="Personal Last.fm statistics dashboard"
)

# Setup templates and static files
templates = Jinja2Templates(directory=str(_PKG_DIR / "templates"))

# Add custom Jinja2 filter for URL encoding
templates.env.filters["urlencode"] = lambda s: quote(str(s), safe="")

app.mount("/static", StaticFiles(directory=str(_PKG_DIR / "static")), name="static")

# Constants
CONSECUTIVE_SCROBBLES_THRESHOLD = 50
# Minimum valid scrobble timestamp: 2000-01-01 00:00:00 UTC
# Last.fm launched in 2002; anything before 2000 is a corrupt epoch artifact.
MINIMUM_VALID_TIMESTAMP = 946684800
MUSICBRAINZ_USER_AGENT = "lytter/1.0 (https://github.com/engeir/lytter)"
MUSICBRAINZ_SEARCH_URL = "https://musicbrainz.org/ws/2/recording/"
DEEZER_SEARCH_URL = "https://api.deezer.com/search"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_SEARCH_URL = "https://api.spotify.com/v1/search"
DURATION_RETRY_DAYS = 30
LYRICS_RETRY_DAYS = 90
GENRES_RETRY_DAYS = 90
METADATA_RETRY_DAYS = 30

_spotify_token: dict[str, object] = {}  # keys: access_token, expires_at

_VARIANT_RE = re.compile(
    r"\s*[-–(]\s*"
    r"(remaster(ed)?|demo|radio\s+edit|acoustic|extended|"
    r"instrumental|remix|single|edit|version|bonus\s+track)\b.*$",
    re.IGNORECASE,
)
_DATE_DOT_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b")


def normalize_text(text: str) -> str:
    """Normalize Unicode text by removing accents and diacritics.

    This allows searching for "u" to match "ü", "Lut" to match "Lüt", etc.
    Uses NFD (Canonical Decomposition) + filtering of combining characters.

    Parameters
    ----------
    text : str
        Text to normalize

    Returns
    -------
    str
        Normalized text with accents removed

    Examples
    --------
    >>> normalize_text("Lüt")
    'Lut'
    >>> normalize_text("café")
    'cafe'
    """
    # NFD = Canonical Decomposition (e.g., "ü" -> "u" + combining diaeresis)
    nfd = unicodedata.normalize("NFD", text)
    # Remove combining characters (accents, diacritics, etc.)
    return "".join(char for char in nfd if unicodedata.category(char) != "Mn")


def init_db():
    """Initialize database with table if it doesn't exist."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS musiclibrary (
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
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS track_durations (
                artist TEXT NOT NULL,
                track TEXT NOT NULL,
                duration_ms INTEGER,
                fetched_at INTEGER NOT NULL,
                PRIMARY KEY (artist, track)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lyrics (
                artist TEXT NOT NULL,
                track TEXT NOT NULL,
                lyrics TEXT,
                fetched_at INTEGER NOT NULL,
                PRIMARY KEY (artist, track)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS artist_genres (
                artist TEXT PRIMARY KEY,
                tags TEXT NOT NULL,
                fetched_at INTEGER NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS track_audio_features (
                artist TEXT NOT NULL,
                track TEXT NOT NULL,
                spotify_id TEXT,
                danceability REAL,
                energy REAL,
                valence REAL,
                tempo REAL,
                acousticness REAL,
                instrumentalness REAL,
                fetched_at INTEGER NOT NULL,
                PRIMARY KEY (artist, track)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS track_metadata (
                artist TEXT NOT NULL,
                track TEXT NOT NULL,
                release_date TEXT,
                popularity INTEGER,
                album_art_url TEXT,
                global_listeners INTEGER,
                global_plays INTEGER,
                fetched_at INTEGER NOT NULL,
                PRIMARY KEY (artist, track)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS artist_metadata (
                artist TEXT PRIMARY KEY,
                bio TEXT,
                similar_artists TEXT,
                fetched_at INTEGER NOT NULL
            )
        """)


init_db()


def format_track_duration(ms: int) -> str:
    """Format milliseconds as M:SS track duration (e.g. 302000 → '5:02')."""
    total_sec = ms // 1000
    return f"{total_sec // 60}:{total_sec % 60:02d}"


def format_listening_time(total_ms: float) -> str:
    """Format milliseconds into human-readable time string."""
    total_min = total_ms / 60_000
    if total_min < 60:  # noqa: PLR2004
        return f"{int(total_min)} min"
    hours = int(total_min // 60)
    mins = int(total_min % 60)
    if hours >= 48:  # noqa: PLR2004
        return f"{hours}h"
    return f"{hours}h {mins}m"


def compute_listening_time(
    conn: sqlite3.Connection,
    tracks_plays: list[tuple[str, str, int]],
) -> tuple[str | None, int, int]:
    """Compute total listening time for (artist, track, play_count) tuples.

    Returns (formatted_time_or_None, known_count, total_unique_count).
    Returns None as time if no cached durations exist yet.
    """
    cursor = conn.cursor()
    total_ms = 0.0
    known = 0
    for artist, track, plays in tracks_plays:
        cursor.execute(
            "SELECT duration_ms FROM track_durations WHERE artist = ? AND track = ?",
            (artist, track),
        )
        row = cursor.fetchone()
        if row and row[0]:
            total_ms += row[0] * plays
            known += 1
    if known == 0:
        return None, 0, len(tracks_plays)
    return format_listening_time(total_ms), known, len(tracks_plays)


def _clean_track_title(title: str) -> str | None:
    """Strip non-live variant suffixes from a track title.

    Removes "- Remastered", "- Demo", "- Radio Edit" etc. so a MusicBrainz
    name search can match the canonical recording. Live tracks are intentionally
    left unchanged — stripping "- Live at..." would return the wrong duration.
    """
    cleaned = _VARIANT_RE.sub("", title).strip()
    return cleaned if cleaned != title else None


def _normalize_title(title: str) -> str:
    """Normalize date separators for consistent API searches.

    Converts dot-separated dates (24.03.23) to slash-separated (24/03/23)
    so Deezer and MusicBrainz can match titles regardless of date format.
    """
    return _DATE_DOT_RE.sub(r"\1/\2/\3", title)


def _fuzzy_cache_lookup(
    conn: sqlite3.Connection, artist: str, track: str
) -> int | None:
    """Check track_durations for a cached entry with a very similar title.

    Returns the cached duration_ms if a title with ≥95% similarity is found,
    allowing date-format variants and minor punctuation differences to reuse
    an already-fetched duration without hitting any external API.
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT track, duration_ms FROM track_durations WHERE artist = ? AND duration_ms IS NOT NULL",
        (artist,),
    )
    for cached_track, cached_ms in cursor.fetchall():
        if fuzz.ratio(track, cached_track) >= 95:  # noqa: PLR2004
            return cached_ms
    return None


def find_similar_tracks(
    conn: sqlite3.Connection,
    artist: str,
    track: str,
    current_duration_ms: int | None,
) -> list[dict]:
    """Find other tracks by the same artist that look like the same recording.

    Criteria (either condition):
    - Title similarity ≥ 95%, OR
    - Title similarity ≥ 50% AND durations within 5 seconds of each other

    Returns list of dicts with keys: track, plays, duration_ms, similarity.
    Excludes the current track itself. Sorted by play count descending.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT m.track, COUNT(*) as plays, td.duration_ms
        FROM musiclibrary m
        LEFT JOIN track_durations td ON td.artist = m.artist AND td.track = m.track
        WHERE m.artist = ?
        GROUP BY m.track
        """,
        (artist,),
    )
    similar = []
    for other_track, plays, other_ms in cursor.fetchall():
        if other_track == track:
            continue
        score = fuzz.ratio(track, other_track)
        duration_match = (
            current_duration_ms is not None
            and other_ms is not None
            and abs(current_duration_ms - other_ms) <= 5_000  # noqa: PLR2004
        )
        if score >= 95 or (score >= 50 and duration_match):  # noqa: PLR2004
            similar.append({
                "track": other_track,
                "plays": plays,
                "duration_ms": other_ms,
                "similarity": round(score),
            })
    return sorted(similar, key=lambda x: x["plays"], reverse=True)


def _mb_name_search(artist: str, track: str) -> int | None:
    """Search MusicBrainz by artist + track name.

    Returns ms or None.
    """
    resp = requests.get(
        MUSICBRAINZ_SEARCH_URL,
        params={
            "query": f'recording:"{track}" AND artist:"{artist}"',
            "fmt": "json",
            "limit": "1",
        },
        headers={"User-Agent": MUSICBRAINZ_USER_AGENT},
        timeout=10,
    )
    if resp.status_code == 200:  # noqa: PLR2004
        recordings = resp.json().get("recordings", [])
        if recordings and recordings[0].get("length"):
            return int(recordings[0]["length"])
    return None


def _deezer_search(artist: str, track: str) -> int | None:
    """Search Deezer by artist + track name.

    Returns ms or None.

    Deezer's search handles title format variations (e.g. "Title - Live at X"
    matches "Title (Live at X)") and covers independent streaming releases well.
    No authentication required.
    """
    resp = requests.get(
        DEEZER_SEARCH_URL,
        params={"q": f'track:"{track}" artist:"{artist}"', "limit": "1"},
        headers={"User-Agent": MUSICBRAINZ_USER_AGENT},
        timeout=10,
    )
    if resp.status_code == 200:  # noqa: PLR2004
        items = resp.json().get("data", [])
        if items and items[0].get("duration"):
            return items[0]["duration"] * 1000  # Deezer returns seconds
    return None


def _spotify_get_token() -> str | None:
    """Return a valid Spotify bearer token, refreshing if needed.

    Returns None if SPOTIFY_CLIENT_ID/SPOTIFY_CLIENT_SECRET are not set or
    if the token request fails.
    """
    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None
    now = _time.time()
    if not _spotify_token or float(str(_spotify_token.get("expires_at", 0))) <= now:
        resp = requests.post(
            SPOTIFY_TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
            timeout=10,
        )
        if resp.status_code != 200:  # noqa: PLR2004
            return None
        data = resp.json()
        _spotify_token["access_token"] = data["access_token"]
        _spotify_token["expires_at"] = now + int(data.get("expires_in", 3600)) - 60
    return str(_spotify_token["access_token"])


def _spotify_search(artist: str, track: str) -> int | None:
    """Search Spotify by artist + track name.

    Returns duration in ms or None. Requires SPOTIFY_CLIENT_ID and
    SPOTIFY_CLIENT_SECRET environment variables; returns None if absent.
    Token is cached in-process until expiry.
    """
    token = _spotify_get_token()
    if not token:
        return None
    resp = requests.get(
        SPOTIFY_SEARCH_URL,
        params={"q": f'track:"{track}" artist:"{artist}"', "type": "track", "limit": "1"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    if resp.status_code == 200:  # noqa: PLR2004
        items = resp.json().get("tracks", {}).get("items", [])
        if items and items[0].get("duration_ms"):
            return int(items[0]["duration_ms"])
    return None


def _fetch_duration_from_mb(artist: str, track: str, mbid: str | None) -> int | None:
    """Fetch track duration using multiple sources in order of preference.

    1. MusicBrainz MBID lookup (exact, fast)
    2. Spotify search (high confidence, broad streaming coverage)
    3. Deezer search (handles variant title formats, covers independent releases)
    4. MusicBrainz name search, full title
    5. MusicBrainz name search, cleaned title (strips "- Remastered" etc.)

    Returns duration in milliseconds, or None if not found anywhere.
    """
    headers = {"User-Agent": MUSICBRAINZ_USER_AGENT}
    # 1. MusicBrainz MBID lookup
    if mbid:
        resp = requests.get(
            f"https://musicbrainz.org/ws/2/recording/{mbid}?fmt=json",
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:  # noqa: PLR2004
            length = resp.json().get("length")
            if length:
                return int(length)
        _time.sleep(1.1)
    search_title = _normalize_title(track)
    # 2. Spotify
    result = _spotify_search(artist, search_title)
    if result:
        return result
    # 3. Deezer
    result = _deezer_search(artist, search_title)
    if result:
        return result
    _time.sleep(1.1)
    # 4. MusicBrainz name search, full title (date-normalized)
    result = _mb_name_search(artist, search_title)
    if result:
        return result
    _time.sleep(1.1)
    # 5. MusicBrainz name search, cleaned title (non-live suffixes stripped)
    cleaned = _clean_track_title(search_title)
    if cleaned:
        result = _mb_name_search(artist, cleaned)
        if result:
            return result
    return None


def fetch_and_cache_durations(tracks: list[tuple[str, str, str | None]]) -> None:
    """Fetch real duration for (artist, track, mbid_or_None) pairs and cache them.

    Tries MusicBrainz MBID lookup, then MusicBrainz name search, then pylast.
    Uses INSERT OR REPLACE so retries can overwrite stale NULL entries.
    """
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        for artist, track, mbid in tracks:
            duration_ms: int | None = None
            try:
                # Check cache first for a near-identical title (e.g. date format variants)
                duration_ms = _fuzzy_cache_lookup(conn, artist, track)
                if duration_ms is None:
                    duration_ms = _fetch_duration_from_mb(artist, track, mbid)
                if duration_ms is None:
                    raw = network.get_track(artist, track).get_duration()
                    duration_ms = int(raw) if raw else None
            except Exception:
                pass
            cursor.execute(
                "INSERT OR REPLACE INTO track_durations (artist, track, duration_ms, fetched_at) VALUES (?, ?, ?, ?)",
                (artist, track, duration_ms, int(_time.time())),
            )
            conn.commit()
            _time.sleep(1.1)  # MusicBrainz rate limit: 1 req/sec


def fetch_and_cache_lyrics(artist: str, track: str) -> None:
    """Fetch lyrics for a track from Genius and cache in the database.

    Requires GENIUS_TOKEN environment variable. Stores NULL if not found so
    the lookup is not retried until LYRICS_RETRY_DAYS have passed.
    """
    genius_token = os.environ.get("GENIUS_TOKEN")
    if not genius_token or _lyricsgenius is None:
        return

    genius = _lyricsgenius.Genius(
        genius_token,
        verbose=False,
        remove_section_headers=False,
        skip_non_songs=True,
    )
    lyrics: str | None = None
    try:
        song = genius.search_song(track, artist)
        if song and song.lyrics:
            # lyricsgenius appends "X Embed" at the end — strip it
            raw = re.sub(r"\d*\s*Embed$", "", song.lyrics.strip()).strip()
            lyrics = raw or None
    except Exception:
        pass
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO lyrics (artist, track, lyrics, fetched_at) VALUES (?, ?, ?, ?)",
            (artist, track, lyrics, int(_time.time())),
        )


def fetch_and_cache_artist_genres(artist: str) -> None:
    """Fetch Last.fm tags for an artist and cache in the database.

    Stores an empty list if the lookup fails, to avoid hammering the API.
    Retried after GENRES_RETRY_DAYS if empty.
    """
    tags: list[dict[str, object]] = []
    try:
        top_tags = network.get_artist(artist).get_top_tags(limit=10)
        tags = [{"tag": str(t.item), "weight": int(t.weight)} for t in top_tags]
    except Exception:
        pass
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO artist_genres (artist, tags, fetched_at) VALUES (?, ?, ?)",
            (artist, json.dumps(tags), int(_time.time())),
        )


def _compute_streaks(conn: sqlite3.Connection) -> tuple[int, int]:
    """Compute current and longest scrobble streaks in days.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.

    Returns
    -------
    tuple[int, int]
        (current_streak, longest_streak)
    """
    rows = conn.execute(
        "SELECT DISTINCT DATE(timestamp, 'unixepoch') FROM musiclibrary ORDER BY 1"
    ).fetchall()
    if not rows:
        return 0, 0
    dates = [datetime.date.fromisoformat(r[0]) for r in rows]
    today = datetime.date.today()
    longest = current = 1
    run = 1
    for i in range(1, len(dates)):
        if (dates[i] - dates[i - 1]).days == 1:
            run += 1
            longest = max(longest, run)
        else:
            run = 1
    # Current streak: count backwards from today
    current = 0
    for d in reversed(dates):
        expected = today - datetime.timedelta(days=current)
        if d == expected:
            current += 1
        elif d == expected - datetime.timedelta(days=1) and current == 0:
            # Last scrobble was yesterday — streak still alive
            current = 1
        else:
            break
    return current, longest


def fetch_and_cache_track_metadata(artist: str, track: str, mbid: str | None = None) -> None:
    """Fetch and cache release date, album art, popularity, and global Last.fm stats.

    Sources tried in order:
    1. Spotify search (art, release_date, popularity) — if configured
    2. MusicBrainz MBID lookup (release_date) — if mbid provided and Spotify missed it
    3. Last.fm (global_listeners, global_plays)

    Always writes a row so the page stops retrying on failure.
    """
    release_date: str | None = None
    popularity: int | None = None
    album_art_url: str | None = None
    global_listeners: int | None = None
    global_plays: int | None = None

    token = _spotify_get_token()
    if token:
        try:
            resp = requests.get(
                SPOTIFY_SEARCH_URL,
                params={"q": f'track:"{track}" artist:"{artist}"', "type": "track", "limit": "1"},
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if resp.status_code == 200:  # noqa: PLR2004
                items = resp.json().get("tracks", {}).get("items", [])
                if items:
                    item = items[0]
                    popularity = item.get("popularity")
                    album = item.get("album", {})
                    release_date = album.get("release_date")
                    images = album.get("images", [])
                    if images:
                        album_art_url = images[0]["url"]
        except Exception:
            pass

    if not release_date and mbid:
        try:
            resp = requests.get(
                f"https://musicbrainz.org/ws/2/recording/{mbid}?fmt=json",
                headers={"User-Agent": MUSICBRAINZ_USER_AGENT},
                timeout=10,
            )
            if resp.status_code == 200:  # noqa: PLR2004
                release_date = resp.json().get("first-release-date")
            _time.sleep(1.1)
        except Exception:
            pass

    try:
        lfm_track = network.get_track(artist, track)
        raw_listeners = lfm_track.get_listener_count()
        raw_plays = lfm_track.get_playcount()
        global_listeners = int(raw_listeners) if raw_listeners else None
        global_plays = int(raw_plays) if raw_plays else None
    except Exception:
        pass

    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO track_metadata
               (artist, track, release_date, popularity, album_art_url,
                global_listeners, global_plays, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (artist, track, release_date, popularity, album_art_url,
             global_listeners, global_plays, int(_time.time())),
        )


def fetch_and_cache_artist_metadata(artist: str) -> None:
    """Fetch and cache artist bio and similar artists from Last.fm.

    Always writes a row (NULLs on failure) so the page stops retrying.
    """
    bio: str | None = None
    similar: list[dict[str, object]] = []
    try:
        lfm_artist = network.get_artist(artist)
        raw_bio = lfm_artist.get_bio_summary()
        if raw_bio:
            # Strip HTML tags
            bio = re.sub(r"<[^>]+>", "", raw_bio).strip() or None
        similar_items = lfm_artist.get_similar(limit=5)
        similar = [
            {"artist": str(s.item), "match": round(float(s.match), 2)}
            for s in similar_items
        ]
    except Exception:
        pass
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO artist_metadata (artist, bio, similar_artists, fetched_at) VALUES (?, ?, ?, ?)",
            (artist, bio, json.dumps(similar), int(_time.time())),
        )


class GetScrobbles:
    """Download and update your scrobbles."""

    def __init__(self):
        self.pause_duration = 0.2
        self.method = "recenttracks"

    def save(self) -> None:
        """Save new scrobbles (incremental update)."""
        self.get_scrobbles()

    def full_update(self) -> None:
        """Full update of scrobbles."""
        self.get_scrobbles(full=True)

    def get_latest_timestamp(self) -> int:
        """Get the most recent timestamp from the database."""
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(timestamp) FROM musiclibrary")
            result = cursor.fetchone()[0]
        return int(result) if result else 0

    def get_scrobbles(
        self,
        limit: int = 200,
        extended: int = 0,
        page: int = 1,
        pages: int = 0,
        *,
        full: bool = False,
    ) -> int:
        """Get scrobbles via the lastfm API.

        Returns the number of new scrobbles added.

        For incremental updates, this will only fetch new scrobbles since the last update.
        For full updates, this will fetch all scrobbles (use with caution).
        """
        url = "https://ws.audioscrobbler.com/2.0/?method=user.get{}&user={}&api_key={}&limit={}&extended={}&page={}&format=json"

        # Get the latest timestamp for incremental updates
        latest_timestamp = 0
        if not full:
            latest_timestamp = self.get_latest_timestamp()
            print(f"Latest timestamp in database: {latest_timestamp}")
            if latest_timestamp > 0:
                # Convert timestamp to readable date for user info
                latest_date = datetime.datetime.fromtimestamp(latest_timestamp)
                print(f"Last scrobble: {latest_date}")

        # Make first request to get total pages
        try:
            request_url = url.format(
                self.method, USER_NAME, API_KEY, limit, extended, page
            )
            response = requests.get(request_url, timeout=30)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"Error fetching from Last.fm API: {e}")
            return 0

        total_pages = int(data[self.method]["@attr"]["totalPages"])
        if pages > 0:
            total_pages = min([total_pages, pages])

        if not full:
            # For incremental updates, limit pages since newest scrobbles come first
            total_pages = min(total_pages, 5)  # Only check first 5 pages
            print(f"Incremental update: checking first {total_pages} pages")
        else:
            print(f"Full update: {total_pages} total pages to retrieve")

        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()

            new_scrobbles_count = 0
            consecutive_old_scrobbles = 0

            # Request each page of data
            for page_ in range(1, int(total_pages) + 1):
                print(f"Page {page_}/{total_pages}", end="\r")
                try:
                    request_url = url.format(
                        self.method, USER_NAME, API_KEY, limit, extended, page_
                    )
                    response = requests.get(request_url, timeout=30)
                    response.raise_for_status()
                    scrobbles = response.json()
                except Exception as e:
                    print(f"\nError fetching page {page_}: {e}")
                    continue

                page_new_count = 0
                for scrobble in scrobbles[self.method]["track"]:
                    # Skip now playing tracks
                    if (
                        "@attr" in scrobble
                        and scrobble["@attr"]["nowplaying"] == "true"
                    ):
                        continue

                    scrobble_timestamp = int(scrobble["date"]["uts"])

                    if scrobble_timestamp < MINIMUM_VALID_TIMESTAMP:
                        print(
                            f"\nSkipping scrobble with corrupt timestamp {scrobble_timestamp} "
                            f"({scrobble['artist']['#text']} - {scrobble['name']})"
                        )
                        continue

                    # Check if this exact scrobble already exists (always check, don't assume based on timestamp)
                    cursor.execute(
                        "SELECT 1 FROM musiclibrary WHERE timestamp = ?",
                        (scrobble_timestamp,),
                    )
                    if cursor.fetchone():
                        # This scrobble exists, but continue checking others (don't skip based on timestamp alone)
                        consecutive_old_scrobbles += 1
                        # Only stop after many consecutive existing scrobbles AND we're past our latest timestamp
                        if (
                            consecutive_old_scrobbles >= CONSECUTIVE_SCROBBLES_THRESHOLD
                            and not full
                            and latest_timestamp > 0
                            and scrobble_timestamp <= latest_timestamp
                        ):
                            print(
                                f"\nFound {consecutive_old_scrobbles} consecutive existing scrobbles beyond latest timestamp, stopping"
                            )
                            return new_scrobbles_count
                        continue

                    # Reset consecutive counter when we find a truly new scrobble
                    consecutive_old_scrobbles = 0

                    # Insert new scrobble
                    try:
                        cursor.execute(
                            """
                            INSERT INTO musiclibrary
                            (artist, artist_mbid, album, album_mbid, track, track_mbid, timestamp)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                            (
                                scrobble["artist"]["#text"],
                                scrobble["artist"]["mbid"],
                                scrobble["album"]["#text"],
                                scrobble["album"]["mbid"],
                                scrobble["name"],
                                scrobble["mbid"],
                                scrobble_timestamp,
                            ),
                        )
                        conn.commit()
                        new_scrobbles_count += 1
                        page_new_count += 1
                    except sqlite3.Error as e:
                        print(f"\nDatabase error: {e}")
                        conn.rollback()

                # For incremental updates, if we found no new scrobbles on this page, likely done
                if not full and page_new_count == 0:
                    print(
                        f"\nNo new scrobbles found on page {page_}, likely up to date"
                    )
                    break

        print(f"\nUpdate complete! Added {new_scrobbles_count} new scrobbles.")
        return new_scrobbles_count


class CurrentStats:
    """Show stats about a given artist."""

    def listening_history_db(self, artist: str):
        """Get the artist listening history as a cumulative line plot."""
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT timestamp FROM musiclibrary WHERE artist = ? ORDER BY timestamp",
                (artist,),
            )
            timestamps = [row[0] for row in cursor.fetchall()]

        dates = [datetime.datetime.fromtimestamp(int(ts)) for ts in timestamps]
        counts = list(range(1, len(dates) + 1))

        df = pd.DataFrame({"date": dates, "count": counts})
        fig = px.line(df, x="date", y="count", title="Listening history")
        fig.update_layout(
            title_x=0.5,
            xaxis_title="Time",
            yaxis_title="Count",
            showlegend=True,
            title_font_family="Open Sans",
            title_font_size=25,
            paper_bgcolor="#161b22",
            plot_bgcolor="#161b22",
            font=dict(color="#f0f6fc"),
            xaxis=dict(gridcolor="#30363d", color="#f0f6fc"),
            yaxis=dict(gridcolor="#30363d", color="#f0f6fc"),
        )

        # Convert to plain dict without binary encoding
        fig_dict = fig.to_dict()
        fig_dict["data"][0]["x"] = [d.strftime("%Y-%m-%dT%H:%M:%S") for d in dates]
        fig_dict["data"][0]["y"] = counts
        return fig_dict

    def top_songs(self, artist: str):
        """Get the top songs of an artist as a bar plot."""
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT track FROM musiclibrary WHERE artist = ?", (artist,))
            tracks = [row[0] for row in cursor.fetchall()]

        songs = OrderedDict(Counter(tracks).most_common())
        unique_songs = list(songs.keys())[::-1]
        song_counts = list(songs.values())[::-1]
        length = max(len(unique_songs) * 30, 100)

        fig = px.bar(
            x=song_counts,
            y=unique_songs,
            orientation="h",
            title="Top songs",
            height=length,
        )
        fig.update_layout(
            title_x=0.5,
            xaxis_title="Count",
            yaxis_title="Track",
            showlegend=True,
            title_font_family="Open Sans",
            title_font_size=25,
            paper_bgcolor="#161b22",
            plot_bgcolor="#161b22",
            font=dict(color="#f0f6fc"),
            xaxis=dict(gridcolor="#30363d", color="#f0f6fc"),
            yaxis=dict(gridcolor="#30363d", color="#f0f6fc"),
        )

        # Convert to plain dict without binary encoding
        fig_dict = fig.to_dict()
        fig_dict["data"][0]["x"] = song_counts
        fig_dict["data"][0]["y"] = unique_songs
        return fig_dict


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Display main dashboard page."""
    # Get basic stats
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM musiclibrary")
        total_scrobbles = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(DISTINCT artist) FROM musiclibrary")
        unique_artists = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(DISTINCT track) FROM musiclibrary")
        unique_tracks = cursor.fetchone()[0]
        cursor.execute(
            "SELECT COUNT(DISTINCT album) FROM musiclibrary WHERE album != ''"
        )
        unique_albums = cursor.fetchone()[0]

        # Compute total listening time using cached durations
        cursor.execute("""
            SELECT m.artist, m.track, COUNT(*) as plays, td.duration_ms
            FROM musiclibrary m
            LEFT JOIN track_durations td ON td.artist = m.artist AND td.track = m.track
            GROUP BY m.artist, m.track
        """)
        rows = cursor.fetchall()
        total_ms = sum(row[2] * row[3] for row in rows if row[3])
        known_track_count = sum(1 for row in rows if row[3])
        total_track_count = len(rows)
        total_listening_time = format_listening_time(total_ms) if known_track_count > 0 else None
        current_streak, longest_streak = _compute_streaks(conn)

    # Get current playing track
    current_track = None
    try:
        user = network.get_user(USER_NAME)
        now_playing = user.get_now_playing()
        if now_playing:
            current_track = {
                "artist": str(now_playing.artist),
                "title": str(now_playing.title),
                "album": str(now_playing.get_album())
                if now_playing.get_album()
                else "Unknown",
            }
    except Exception:
        pass

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "total_scrobbles": total_scrobbles,
            "unique_artists": unique_artists,
            "unique_tracks": unique_tracks,
            "unique_albums": unique_albums,
            "current_track": current_track,
            "total_listening_time": total_listening_time,
            "listening_time_known_tracks": known_track_count,
            "listening_time_total_tracks": total_track_count,
            "current_streak": current_streak,
            "longest_streak": longest_streak,
        },
    )


@app.get("/artist/{artist_name}", response_class=HTMLResponse)
async def artist_stats(
    request: Request, artist_name: str, background_tasks: BackgroundTasks
):
    """Artist statistics page."""
    stats = CurrentStats()

    # Get listening history (already returns plain dict)
    history_json = json.dumps(stats.listening_history_db(artist_name))

    # Get basic artist stats and duration data
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT COUNT(*) FROM musiclibrary WHERE artist = ?", (artist_name,)
        )
        total_plays = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(DISTINCT track) FROM musiclibrary WHERE artist = ?",
            (artist_name,),
        )
        unique_tracks = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(DISTINCT album) FROM musiclibrary WHERE artist = ? AND album != ''",
            (artist_name,),
        )
        unique_albums = cursor.fetchone()[0]

        first_heard_ts = cursor.execute(
            "SELECT MIN(timestamp) FROM musiclibrary WHERE artist = ?", (artist_name,)
        ).fetchone()[0]
        first_heard = (
            datetime.datetime.fromtimestamp(first_heard_ts).strftime("%-d %B %Y")
            if first_heard_ts else None
        )

        # Get per-track play counts and durations
        cursor.execute(
            """
            SELECT m.track, COUNT(*) as plays, MAX(m.track_mbid) as mbid, td.duration_ms
            FROM musiclibrary m
            LEFT JOIN track_durations td ON td.artist = m.artist AND td.track = m.track
            WHERE m.artist = ?
            GROUP BY m.track
            """,
            (artist_name,),
        )
        track_rows = cursor.fetchall()

        tracks_plays = [(artist_name, row[0], row[1]) for row in track_rows]
        listening_time, known_tracks, total_unique_tracks = compute_listening_time(
            conn, tracks_plays
        )

        # Find tracks not yet attempted, plus stale NULL entries to retry
        stale_cutoff = int(_time.time()) - DURATION_RETRY_DAYS * 86_400
        cursor.execute(
            "SELECT track FROM track_durations WHERE artist = ?", (artist_name,)
        )
        cached_tracks = {row[0] for row in cursor.fetchall()}
        cursor.execute(
            "SELECT track FROM track_durations WHERE artist = ? AND duration_ms IS NULL AND fetched_at < ?",
            (artist_name, stale_cutoff),
        )
        stale_tracks = {row[0] for row in cursor.fetchall()}
        if stale_tracks:
            cursor.execute(
                f"DELETE FROM track_durations WHERE artist = ? AND track IN ({','.join('?' * len(stale_tracks))})",  # noqa: S608
                (artist_name, *stale_tracks),
            )
        missing = [
            (artist_name, row[0], row[2] or None)
            for row in track_rows
            if row[0] not in cached_tracks or row[0] in stale_tracks
        ][:10]

    if missing:
        background_tasks.add_task(fetch_and_cache_durations, missing)

    # Genre tags
    with sqlite3.connect(DB_NAME) as conn:
        genre_row = conn.execute(
            "SELECT tags, fetched_at FROM artist_genres WHERE artist = ?",
            (artist_name,),
        ).fetchone()
    if genre_row is None:
        background_tasks.add_task(fetch_and_cache_artist_genres, artist_name)
        genres: list[dict[str, object]] = []
        genres_fetched = False
    else:
        genres = json.loads(genre_row[0])
        genres_fetched = True
        if not genres and _time.time() - genre_row[1] > GENRES_RETRY_DAYS * 86_400:
            with sqlite3.connect(DB_NAME) as conn:
                conn.execute("DELETE FROM artist_genres WHERE artist = ?", (artist_name,))
            background_tasks.add_task(fetch_and_cache_artist_genres, artist_name)
            genres_fetched = False

    # Artist metadata (bio + similar artists)
    with sqlite3.connect(DB_NAME) as conn:
        meta_row = conn.execute(
            "SELECT bio, similar_artists, fetched_at FROM artist_metadata WHERE artist = ?",
            (artist_name,),
        ).fetchone()
    if meta_row is None:
        background_tasks.add_task(fetch_and_cache_artist_metadata, artist_name)
        artist_bio: str | None = None
        artist_similar: list[dict[str, object]] = []
        artist_metadata_fetched = False
    else:
        artist_bio = meta_row[0]
        artist_similar = json.loads(meta_row[1]) if meta_row[1] else []
        artist_metadata_fetched = True
        if not artist_bio and not artist_similar and _time.time() - meta_row[2] > METADATA_RETRY_DAYS * 86_400:
            with sqlite3.connect(DB_NAME) as conn:
                conn.execute("DELETE FROM artist_metadata WHERE artist = ?", (artist_name,))
            background_tasks.add_task(fetch_and_cache_artist_metadata, artist_name)
            artist_metadata_fetched = False

    return templates.TemplateResponse(
        request,
        "artist.html",
        {
            "artist_name": artist_name,
            "total_plays": total_plays,
            "unique_tracks": unique_tracks,
            "unique_albums": unique_albums,
            "history_chart": history_json,
            "listening_time": listening_time,
            "known_tracks": known_tracks,
            "total_unique_tracks": total_unique_tracks,
            "genres": genres,
            "genres_fetched": genres_fetched,
            "first_heard": first_heard,
            "bio": artist_bio,
            "similar_artists": artist_similar,
            "artist_metadata_fetched": artist_metadata_fetched,
        },
    )


@app.get("/top-artists")
async def top_artists():
    """Get top artists data (JSON for backwards compatibility)."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT artist, COUNT(*) as plays FROM musiclibrary GROUP BY artist ORDER BY plays DESC LIMIT 50"
        )
        result = cursor.fetchall()

    artists = [{"artist": row[0], "plays": row[1]} for row in result]
    return {"artists": artists}


@app.get("/html/top-artists", response_class=HTMLResponse)
async def top_artists_html(request: Request):
    """Get top artists as HTML fragment for HTMX."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT artist, COUNT(*) as plays FROM musiclibrary GROUP BY artist ORDER BY plays DESC LIMIT 50"
        )
        result = cursor.fetchall()

    artists = [{"artist": row[0], "plays": row[1]} for row in result]
    return templates.TemplateResponse(
        request, "_top_artists_list.html", {"artists": artists}
    )


@app.get("/charts/listening-timeline")
async def listening_timeline():
    """Generate listening timeline chart."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()

        # Get daily scrobble counts for the last 365 days
        cursor.execute("""
            SELECT DATE(timestamp, 'unixepoch') as date, COUNT(*) as plays
            FROM musiclibrary
            WHERE timestamp >= strftime('%s', 'now', '-365 days')
            GROUP BY date
            ORDER BY date ASC
        """)
        result = cursor.fetchall()

    df = pd.DataFrame(result, columns=["date", "plays"])
    df["date"] = pd.to_datetime(df["date"])
    df["rolling7"] = df["plays"].rolling(7, center=True, min_periods=1).mean()

    dates = df["date"].dt.strftime("%Y-%m-%dT%H:%M:%S").tolist()

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            x=dates,
            y=df["plays"].tolist(),
            name="Daily plays",
            marker_color="#1f6feb",
            marker_opacity=0.6,
            hovertemplate="%{y} scrobbles<extra></extra>",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=dates,
            y=df["rolling7"].round(1).tolist(),
            name="7-day avg",
            mode="lines",
            line=dict(color="#f78166", width=2),
            hovertemplate="%{y} avg<extra></extra>",
        )
    )

    if len(df) > 0:
        peak_idx = int(df["plays"].idxmax())
        peak_date = dates[peak_idx]
        peak_val = int(df["plays"].iloc[peak_idx])
        fig.add_annotation(
            x=peak_date,
            y=peak_val,
            text=f"Peak: {peak_val}",
            showarrow=True,
            arrowhead=2,
            arrowcolor="#f0f6fc",
            arrowwidth=1.5,
            ax=0,
            ay=-36,
            font=dict(color="#f0f6fc", size=12),
            bgcolor="#30363d",
            bordercolor="#58a6ff",
            borderwidth=1,
            borderpad=4,
        )

    # Calculate initial view range (last 30 days)
    if len(df) > 0:
        max_date = df["date"].max()
        min_date = df["date"].min()
        initial_end = max_date
        initial_start = max_date - pd.Timedelta(days=90)
        initial_start = max(initial_start, min_date)
    else:
        initial_start = initial_end = None

    fig.update_layout(
        title="Daily Listening Activity (Last 365 Days)",
        xaxis_title="Date",
        yaxis_title="Number of Scrobbles",
        paper_bgcolor="#161b22",
        plot_bgcolor="#161b22",
        font=dict(color="#f0f6fc"),
        legend=dict(
            bgcolor="#0d1117",
            bordercolor="#30363d",
            borderwidth=1,
            font=dict(color="#f0f6fc"),
        ),
        bargap=0.1,
        xaxis=dict(
            gridcolor="#30363d",
            color="#f0f6fc",
            range=[initial_start, initial_end] if initial_start else None,
            rangeslider=dict(
                visible=True,
                bgcolor="#0d1117",
                bordercolor="#30363d",
                borderwidth=1,
                thickness=0.4,
            ),
            rangeselector=dict(
                buttons=[
                    dict(count=7, label="1w", step="day", stepmode="backward"),
                    dict(count=14, label="2w", step="day", stepmode="backward"),
                    dict(count=1, label="1m", step="month", stepmode="backward"),
                    dict(count=3, label="3m", step="month", stepmode="backward"),
                    dict(count=6, label="6m", step="month", stepmode="backward"),
                    dict(step="all", label="All"),
                ],
                bgcolor="#161b22",
                activecolor="#238636",
                bordercolor="#30363d",
                borderwidth=1,
                font=dict(color="#f0f6fc"),
            ),
        ),
        yaxis=dict(gridcolor="#30363d", color="#f0f6fc"),
        hovermode="x unified",
    )

    return fig.to_dict()


@app.get("/recent-stats")
async def recent_stats():
    """Get top artists, albums, and songs from past week and month (JSON)."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()

        # Top 5 artists from past week
        cursor.execute("""
            SELECT artist, COUNT(*) as plays
            FROM musiclibrary
            WHERE timestamp >= strftime('%s', 'now', '-7 days')
            GROUP BY artist
            ORDER BY plays DESC
            LIMIT 5
        """)
        week_artists = [
            {"artist": row[0], "plays": row[1]} for row in cursor.fetchall()
        ]

        # Top 5 albums from past week
        cursor.execute("""
            SELECT artist, album, COUNT(*) as plays
            FROM musiclibrary
            WHERE timestamp >= strftime('%s', 'now', '-7 days')
                AND album != ''
            GROUP BY artist, album
            ORDER BY plays DESC
            LIMIT 5
        """)
        week_albums = [
            {"artist": row[0], "album": row[1], "plays": row[2]}
            for row in cursor.fetchall()
        ]

        # Top 5 songs from past week
        cursor.execute("""
            SELECT artist, track, COUNT(*) as plays
            FROM musiclibrary
            WHERE timestamp >= strftime('%s', 'now', '-7 days')
            GROUP BY artist, track
            ORDER BY plays DESC
            LIMIT 5
        """)
        week_songs = [
            {"artist": row[0], "track": row[1], "plays": row[2]}
            for row in cursor.fetchall()
        ]

        # Top 5 artists from past month
        cursor.execute("""
            SELECT artist, COUNT(*) as plays
            FROM musiclibrary
            WHERE timestamp >= strftime('%s', 'now', '-30 days')
            GROUP BY artist
            ORDER BY plays DESC
            LIMIT 5
        """)
        month_artists = [
            {"artist": row[0], "plays": row[1]} for row in cursor.fetchall()
        ]

        # Top 5 albums from past month
        cursor.execute("""
            SELECT artist, album, COUNT(*) as plays
            FROM musiclibrary
            WHERE timestamp >= strftime('%s', 'now', '-30 days')
                AND album != ''
            GROUP BY artist, album
            ORDER BY plays DESC
            LIMIT 5
        """)
        month_albums = [
            {"artist": row[0], "album": row[1], "plays": row[2]}
            for row in cursor.fetchall()
        ]

        # Top 5 songs from past month
        cursor.execute("""
            SELECT artist, track, COUNT(*) as plays
            FROM musiclibrary
            WHERE timestamp >= strftime('%s', 'now', '-30 days')
            GROUP BY artist, track
            ORDER BY plays DESC
            LIMIT 5
        """)
        month_songs = [
            {"artist": row[0], "track": row[1], "plays": row[2]}
            for row in cursor.fetchall()
        ]

    return {
        "week_artists": week_artists,
        "week_albums": week_albums,
        "week_songs": week_songs,
        "month_artists": month_artists,
        "month_albums": month_albums,
        "month_songs": month_songs,
    }


@app.get("/html/recent-favorites", response_class=HTMLResponse)
async def recent_favorites_html(request: Request):
    """Get recent favorites as HTML fragment for HTMX."""
    # Reuse the same query logic
    stats = await recent_stats()
    return templates.TemplateResponse(
        request, "_recent_favorites.html", {**stats}
    )


@app.get("/artist-top-songs")
async def artist_top_songs(artist: str):
    """Get top songs for a specific artist."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT track, COUNT(*) as plays
            FROM musiclibrary
            WHERE artist = ?
            GROUP BY track
            ORDER BY plays DESC
            LIMIT 100
        """,
            (artist,),
        )
        result = cursor.fetchall()

    songs = [{"track": row[0], "plays": row[1]} for row in result]
    return {"songs": songs}


@app.get("/artist-top-albums")
async def artist_top_albums(artist: str):
    """Get top albums for a specific artist."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT album, COUNT(*) as plays
            FROM musiclibrary
            WHERE artist = ? AND album != ''
            GROUP BY album
            ORDER BY plays DESC
            LIMIT 100
        """,
            (artist,),
        )
        result = cursor.fetchall()

    albums = [{"album": row[0], "plays": row[1]} for row in result]
    return {"albums": albums}


@app.get("/album/{artist_name}/{album_name:path}", response_class=HTMLResponse)
async def album_stats(
    request: Request,
    artist_name: str,
    album_name: str,
    background_tasks: BackgroundTasks,
):
    """Album statistics page."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()

        # Get album stats
        cursor.execute(
            "SELECT COUNT(*) FROM musiclibrary WHERE artist = ? AND album = ?",
            (artist_name, album_name),
        )
        total_plays = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(DISTINCT track) FROM musiclibrary WHERE artist = ? AND album = ?",
            (artist_name, album_name),
        )
        unique_tracks = cursor.fetchone()[0]

        # Get per-track play counts and durations for this album
        cursor.execute(
            """
            SELECT m.track, COUNT(*) as plays, MAX(m.track_mbid) as mbid, td.duration_ms
            FROM musiclibrary m
            LEFT JOIN track_durations td ON td.artist = m.artist AND td.track = m.track
            WHERE m.artist = ? AND m.album = ?
            GROUP BY m.track
            """,
            (artist_name, album_name),
        )
        track_rows = cursor.fetchall()

        tracks_plays = [(artist_name, row[0], row[1]) for row in track_rows]
        listening_time, known_tracks, total_unique_tracks = compute_listening_time(
            conn, tracks_plays
        )

        first_heard_ts = cursor.execute(
            "SELECT MIN(timestamp) FROM musiclibrary WHERE artist = ? AND album = ?",
            (artist_name, album_name),
        ).fetchone()[0]
        first_heard = (
            datetime.datetime.fromtimestamp(first_heard_ts).strftime("%-d %B %Y")
            if first_heard_ts else None
        )

        # Best-effort album art from any cached track in this album
        art_row = cursor.execute(
            """SELECT tm.album_art_url FROM track_metadata tm
               JOIN musiclibrary m ON m.artist = tm.artist AND m.track = tm.track
               WHERE m.artist = ? AND m.album = ? AND tm.album_art_url IS NOT NULL
               LIMIT 1""",
            (artist_name, album_name),
        ).fetchone()
        album_art_url = art_row[0] if art_row else None

        stale_cutoff = int(_time.time()) - DURATION_RETRY_DAYS * 86_400
        cursor.execute(
            "SELECT track FROM track_durations WHERE artist = ?", (artist_name,)
        )
        cached_tracks = {row[0] for row in cursor.fetchall()}
        cursor.execute(
            "SELECT track FROM track_durations WHERE artist = ? AND duration_ms IS NULL AND fetched_at < ?",
            (artist_name, stale_cutoff),
        )
        stale_tracks = {row[0] for row in cursor.fetchall()}
        if stale_tracks:
            cursor.execute(
                f"DELETE FROM track_durations WHERE artist = ? AND track IN ({','.join('?' * len(stale_tracks))})",  # noqa: S608
                (artist_name, *stale_tracks),
            )
        missing = [
            (artist_name, row[0], row[2] or None)
            for row in track_rows
            if row[0] not in cached_tracks or row[0] in stale_tracks
        ]

        # Get listening history
        cursor.execute(
            """
            SELECT timestamp FROM musiclibrary
            WHERE artist = ? AND album = ?
            ORDER BY timestamp
        """,
            (artist_name, album_name),
        )
        timestamps = [row[0] for row in cursor.fetchall()]

    dates = [datetime.datetime.fromtimestamp(int(ts)) for ts in timestamps]
    counts = list(range(1, len(dates) + 1))

    df = pd.DataFrame({"date": dates, "count": counts})
    fig = px.line(df, x="date", y="count", title="Listening history")
    fig.update_layout(
        title_x=0.5,
        xaxis_title="Time",
        yaxis_title="Count",
        showlegend=True,
        title_font_family="Open Sans",
        title_font_size=25,
        paper_bgcolor="#161b22",
        plot_bgcolor="#161b22",
        font=dict(color="#f0f6fc"),
        xaxis=dict(gridcolor="#30363d", color="#f0f6fc"),
        yaxis=dict(gridcolor="#30363d", color="#f0f6fc"),
    )

    fig_dict = fig.to_dict()
    fig_dict["data"][0]["x"] = [d.strftime("%Y-%m-%dT%H:%M:%S") for d in dates]
    fig_dict["data"][0]["y"] = counts
    history_json = json.dumps(fig_dict)

    if missing:
        background_tasks.add_task(fetch_and_cache_durations, missing)

    return templates.TemplateResponse(
        request,
        "album.html",
        {
            "artist_name": artist_name,
            "album_name": album_name,
            "total_plays": total_plays,
            "unique_tracks": unique_tracks,
            "history_chart": history_json,
            "listening_time": listening_time,
            "known_tracks": known_tracks,
            "total_unique_tracks": total_unique_tracks,
            "first_heard": first_heard,
            "album_art_url": album_art_url,
        },
    )


@app.get("/song/{artist_name}/{track_name:path}", response_class=HTMLResponse)
async def song_stats(
    request: Request,
    artist_name: str,
    track_name: str,
    background_tasks: BackgroundTasks,
):
    """Song statistics page."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()

        # Get song stats
        cursor.execute(
            "SELECT COUNT(*) FROM musiclibrary WHERE artist = ? AND track = ?",
            (artist_name, track_name),
        )
        total_plays = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT COUNT(DISTINCT album) FROM musiclibrary
            WHERE artist = ? AND track = ? AND album != ''
        """,
            (artist_name, track_name),
        )
        unique_albums = cursor.fetchone()[0]

        first_heard_ts = cursor.execute(
            "SELECT MIN(timestamp) FROM musiclibrary WHERE artist = ? AND track = ?",
            (artist_name, track_name),
        ).fetchone()[0]
        first_heard = (
            datetime.datetime.fromtimestamp(first_heard_ts).strftime("%-d %B %Y")
            if first_heard_ts else None
        )

        # Look up cached duration for this track
        cursor.execute(
            "SELECT duration_ms, fetched_at FROM track_durations WHERE artist = ? AND track = ?",
            (artist_name, track_name),
        )
        duration_row = cursor.fetchone()

        cursor.execute(
            "SELECT MAX(track_mbid) FROM musiclibrary WHERE artist = ? AND track = ?",
            (artist_name, track_name),
        )
        mbid_row = cursor.fetchone()
        mbid = mbid_row[0] if mbid_row else None

        if duration_row is None:
            # Not yet fetched — schedule background fetch
            background_tasks.add_task(
                fetch_and_cache_durations, [(artist_name, track_name, mbid)]
            )
            listening_time = None
            duration_fetched = False
        elif duration_row[0]:
            listening_time = format_listening_time(duration_row[0] * total_plays)
            duration_fetched = True
        else:
            # Previously fetched but unknown — retry if stale
            listening_time = None
            duration_fetched = True
            if _time.time() - duration_row[1] > DURATION_RETRY_DAYS * 86_400:
                cursor.execute(
                    "DELETE FROM track_durations WHERE artist = ? AND track = ?",
                    (artist_name, track_name),
                )
                background_tasks.add_task(
                    fetch_and_cache_durations, [(artist_name, track_name, mbid)]
                )

        # Lyrics: check cache, schedule background fetch if missing/stale
        lyrics_row = cursor.execute(
            "SELECT lyrics, fetched_at FROM lyrics WHERE artist = ? AND track = ?",
            (artist_name, track_name),
        ).fetchone()
        if lyrics_row is None:
            if os.environ.get("GENIUS_TOKEN"):
                background_tasks.add_task(fetch_and_cache_lyrics, artist_name, track_name)
            lyrics = None
            lyrics_fetched = False
        elif lyrics_row[0] is not None:
            lyrics = lyrics_row[0]
            lyrics_fetched = True
        else:
            # Previously attempted but not found — retry if stale
            lyrics = None
            lyrics_fetched = True
            if _time.time() - lyrics_row[1] > LYRICS_RETRY_DAYS * 86_400:
                cursor.execute(
                    "DELETE FROM lyrics WHERE artist = ? AND track = ?",
                    (artist_name, track_name),
                )
                if os.environ.get("GENIUS_TOKEN"):
                    background_tasks.add_task(fetch_and_cache_lyrics, artist_name, track_name)
                lyrics_fetched = False

        # Track metadata (release date, art, popularity, global stats)
        meta_row = cursor.execute(
            """SELECT release_date, popularity, album_art_url, global_listeners,
                      global_plays, fetched_at FROM track_metadata
               WHERE artist = ? AND track = ?""",
            (artist_name, track_name),
        ).fetchone()
        if meta_row is None:
            background_tasks.add_task(fetch_and_cache_track_metadata, artist_name, track_name, mbid)
            track_meta: dict[str, object] | None = None
            track_meta_fetched = False
        else:
            track_meta_fetched = True
            if any(v is not None for v in meta_row[:5]):
                track_meta = {
                    "release_date": meta_row[0],
                    "popularity": meta_row[1],
                    "album_art_url": meta_row[2],
                    "global_listeners": meta_row[3],
                    "global_plays": meta_row[4],
                }
            else:
                track_meta = None
                if _time.time() - meta_row[5] > METADATA_RETRY_DAYS * 86_400:
                    cursor.execute(
                        "DELETE FROM track_metadata WHERE artist = ? AND track = ?",
                        (artist_name, track_name),
                    )
                    background_tasks.add_task(fetch_and_cache_track_metadata, artist_name, track_name, mbid)
                    track_meta_fetched = False

        # Find similar recordings (variants of the same performance)
        current_duration_ms = duration_row[0] if duration_row and duration_row[0] else None
        track_duration = format_track_duration(current_duration_ms) if current_duration_ms else None
        similar_tracks = find_similar_tracks(conn, artist_name, track_name, current_duration_ms)
        combined_plays = total_plays + sum(t["plays"] for t in similar_tracks)
        combined_time = (
            format_listening_time(current_duration_ms * combined_plays)
            if current_duration_ms
            else None
        )

        # Get listening history
        cursor.execute(
            """
            SELECT timestamp FROM musiclibrary
            WHERE artist = ? AND track = ?
            ORDER BY timestamp
        """,
            (artist_name, track_name),
        )
        timestamps = [row[0] for row in cursor.fetchall()]

    dates = [datetime.datetime.fromtimestamp(int(ts)) for ts in timestamps]
    counts = list(range(1, len(dates) + 1))

    df = pd.DataFrame({"date": dates, "count": counts})
    fig = px.line(df, x="date", y="count", title="Listening history")
    fig.update_layout(
        title_x=0.5,
        xaxis_title="Time",
        yaxis_title="Count",
        showlegend=True,
        title_font_family="Open Sans",
        title_font_size=25,
        paper_bgcolor="#161b22",
        plot_bgcolor="#161b22",
        font=dict(color="#f0f6fc"),
        xaxis=dict(gridcolor="#30363d", color="#f0f6fc"),
        yaxis=dict(gridcolor="#30363d", color="#f0f6fc"),
    )

    fig_dict = fig.to_dict()
    fig_dict["data"][0]["x"] = [d.strftime("%Y-%m-%dT%H:%M:%S") for d in dates]
    fig_dict["data"][0]["y"] = counts
    history_json = json.dumps(fig_dict)

    return templates.TemplateResponse(
        request,
        "song.html",
        {
            "artist_name": artist_name,
            "track_name": track_name,
            "total_plays": total_plays,
            "unique_albums": unique_albums,
            "history_chart": history_json,
            "listening_time": listening_time,
            "duration_fetched": duration_fetched,
            "track_duration": track_duration,
            "similar_tracks": similar_tracks,
            "combined_plays": combined_plays,
            "combined_time": combined_time,
            "lyrics": lyrics,
            "lyrics_fetched": lyrics_fetched,
            "first_heard": first_heard,
            "track_meta": track_meta,
            "track_meta_fetched": track_meta_fetched,
        },
    )


@app.get("/album-tracks")
async def album_tracks(artist: str, album: str):
    """Get tracks from a specific album."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT track, COUNT(*) as plays
            FROM musiclibrary
            WHERE artist = ? AND album = ?
            GROUP BY track
            ORDER BY plays DESC
            LIMIT 100
        """,
            (artist, album),
        )
        result = cursor.fetchall()

    tracks = [{"track": row[0], "plays": row[1]} for row in result]
    return {"tracks": tracks}


@app.get("/api/search/artists")
async def search_artists(q: str = "", limit: int = 10) -> dict:
    """Search artists with fuzzy matching and Unicode normalization.

    Uses rapidfuzz for fuzzy matching and Unicode normalization for accent-insensitive search.

    Parameters
    ----------
    q : str
        Search query (minimum 2 characters)
    limit : int
        Maximum number of results to return (default: 10)

    Returns
    -------
    dict
        Dictionary with 'results' key containing list of matching artists
        Each result has: artist (name), plays (count), similarity (0-100 score)
    """
    min_query_length = 2
    if not q or len(q) < min_query_length:
        return {"results": []}

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()

        # Get all artists with their play counts
        cursor.execute("""
            SELECT artist, COUNT(*) as plays
            FROM musiclibrary
            GROUP BY artist
        """)
        all_artists = {row[0]: row[1] for row in cursor.fetchall()}

    if not all_artists:
        return {"results": []}

    # Normalize query for accent-insensitive matching (ü -> u, é -> e, etc.)
    q_lower = q.lower()
    q_normalized = normalize_text(q_lower)

    # Combine multiple matching strategies for best results
    results_dict = {}

    # Strategy 1: Exact substring match (case-insensitive + accent-insensitive)
    for artist, plays in all_artists.items():
        artist_lower = artist.lower()
        artist_normalized = normalize_text(artist_lower)

        # Check both regular and normalized versions for maximum compatibility
        if q_lower in artist_lower or q_normalized in artist_normalized:
            # Perfect substring match gets 100 similarity
            results_dict[artist] = {
                "artist": artist,
                "plays": plays,
                "similarity": 100.0,
            }

    # Strategy 2: Fuzzy matching for artists not already matched
    remaining_artists = [a for a in all_artists.keys() if a not in results_dict]
    if remaining_artists:
        matches: list[tuple[str, float, int]] = process.extract(
            q,
            remaining_artists,
            scorer=fuzz.WRatio,  # Weighted ratio for fuzzy matches
            limit=limit * 2,
            score_cutoff=60,  # Only decent matches
        )

        for match in matches:
            artist = match[0]
            results_dict[artist] = {
                "artist": artist,
                "plays": all_artists[artist],
                "similarity": round(match[1], 1),
            }

    # Convert to list
    results = list(results_dict.values())

    # Sort by:
    # 1. Similarity score (higher is better)
    # 2. Play count (more popular is better as tiebreaker)
    results.sort(key=lambda x: (x["similarity"], x["plays"]), reverse=True)

    # Limit to requested number
    return {"results": results[:limit]}


@app.get("/api/search/all")
async def search_all(q: str = "", limit: int = 5) -> dict:
    """Search artists, albums, and tracks with substring matching.

    Parameters
    ----------
    q : str
        Search query (minimum 2 characters)
    limit : int
        Maximum results per category (default: 5)

    Returns
    -------
    dict
        Keys 'artists', 'albums', 'tracks', each a list of matching items.
    """
    min_query_length = 2
    if not q or len(q) < min_query_length:
        return {"artists": [], "albums": [], "tracks": []}

    q_lower = q.lower()
    q_norm = normalize_text(q_lower)

    with sqlite3.connect(DB_NAME) as conn:
        conn.create_function("NORM", 1, lambda s: normalize_text(s.lower()) if s else "")

        artist_rows = conn.execute(
            """SELECT artist, COUNT(*) as plays FROM musiclibrary
               WHERE NORM(artist) LIKE ? GROUP BY artist ORDER BY plays DESC LIMIT ?""",
            (f"%{q_norm}%", limit),
        ).fetchall()

        album_rows = conn.execute(
            """SELECT artist, album, COUNT(*) as plays FROM musiclibrary
               WHERE album != '' AND NORM(album) LIKE ?
               GROUP BY artist, album ORDER BY plays DESC LIMIT ?""",
            (f"%{q_norm}%", limit),
        ).fetchall()

        track_rows = conn.execute(
            """SELECT artist, track, COUNT(*) as plays FROM musiclibrary
               WHERE NORM(track) LIKE ?
               GROUP BY artist, track ORDER BY plays DESC LIMIT ?""",
            (f"%{q_norm}%", limit),
        ).fetchall()

    return {
        "artists": [{"artist": r[0], "plays": r[1]} for r in artist_rows],
        "albums": [{"artist": r[0], "album": r[1], "plays": r[2]} for r in album_rows],
        "tracks": [{"artist": r[0], "track": r[1], "plays": r[2]} for r in track_rows],
    }


@app.get("/yearly", response_class=HTMLResponse)
async def yearly_stats(request: Request):
    """Yearly statistics page with year selector."""
    # Get available years from database
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT strftime('%Y', timestamp, 'unixepoch') as year
            FROM musiclibrary
            ORDER BY year DESC
        """)
        years = [row[0] for row in cursor.fetchall()]

    return templates.TemplateResponse(
        request,
        "yearly.html",
        {
            "years": years,
            "current_year": years[0] if years else None,
        },
    )


@app.get("/api/yearly/top-items")
async def yearly_top_items(year: int, limit: int = 20):
    """Get top songs, albums, and artists for a specific year."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()

        # Top songs
        cursor.execute(
            """
            SELECT artist, track, COUNT(*) as plays
            FROM musiclibrary
            WHERE strftime('%Y', timestamp, 'unixepoch') = ?
            GROUP BY artist, track
            ORDER BY plays DESC
            LIMIT ?
        """,
            (str(year), limit),
        )
        top_songs = [
            {"artist": row[0], "track": row[1], "plays": row[2]}
            for row in cursor.fetchall()
        ]

        # Top albums
        cursor.execute(
            """
            SELECT artist, album, COUNT(*) as plays
            FROM musiclibrary
            WHERE strftime('%Y', timestamp, 'unixepoch') = ?
                AND album != ''
            GROUP BY artist, album
            ORDER BY plays DESC
            LIMIT ?
        """,
            (str(year), limit),
        )
        top_albums = [
            {"artist": row[0], "album": row[1], "plays": row[2]}
            for row in cursor.fetchall()
        ]

        # Top artists
        cursor.execute(
            """
            SELECT artist, COUNT(*) as plays
            FROM musiclibrary
            WHERE strftime('%Y', timestamp, 'unixepoch') = ?
            GROUP BY artist
            ORDER BY plays DESC
            LIMIT ?
        """,
            (str(year), limit),
        )
        top_artists = [{"artist": row[0], "plays": row[1]} for row in cursor.fetchall()]

    return {
        "songs": top_songs,
        "albums": top_albums,
        "artists": top_artists,
    }


@app.get("/html/yearly/top-items/{item_type}", response_class=HTMLResponse)
async def yearly_top_items_html(
    request: Request, item_type: str, year: int, limit: int = 20
):
    """Get top items as HTML fragment for HTMX (songs, albums, or artists)."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()

        if item_type == "songs":
            cursor.execute(
                """
                SELECT artist, track, COUNT(*) as plays
                FROM musiclibrary
                WHERE strftime('%Y', timestamp, 'unixepoch') = ?
                GROUP BY artist, track
                ORDER BY plays DESC
                LIMIT ?
            """,
                (str(year), limit),
            )
            items = [
                {"artist": row[0], "track": row[1], "plays": row[2]}
                for row in cursor.fetchall()
            ]
        elif item_type == "albums":
            cursor.execute(
                """
                SELECT artist, album, COUNT(*) as plays
                FROM musiclibrary
                WHERE strftime('%Y', timestamp, 'unixepoch') = ?
                    AND album != ''
                GROUP BY artist, album
                ORDER BY plays DESC
                LIMIT ?
            """,
                (str(year), limit),
            )
            items = [
                {"artist": row[0], "album": row[1], "plays": row[2]}
                for row in cursor.fetchall()
            ]
        elif item_type == "artists":
            cursor.execute(
                """
                SELECT artist, COUNT(*) as plays
                FROM musiclibrary
                WHERE strftime('%Y', timestamp, 'unixepoch') = ?
                GROUP BY artist
                ORDER BY plays DESC
                LIMIT ?
            """,
                (str(year), limit),
            )
            items = [{"artist": row[0], "plays": row[1]} for row in cursor.fetchall()]
        else:
            return HTMLResponse(content="<p class='text-muted'>Invalid item type</p>")

    return templates.TemplateResponse(
        request,
        "_yearly_top_items.html",
        {"items": items, "item_type": item_type},
    )


@app.get("/duration-stats", response_class=HTMLResponse)
async def duration_stats_page(request: Request):
    """Duration-based statistics page."""
    return templates.TemplateResponse(request, "duration_stats.html", {})


@app.get("/compare", response_class=HTMLResponse)
async def compare_page(request: Request):
    """Artist comparison page."""
    return templates.TemplateResponse(request, "compare.html", {})


@app.get("/api/compare/artists")
async def compare_artists(artists: list[str] = Query(default=[])):  # noqa: B008
    """Return comparison stats for up to 5 artists."""
    artists = artists[:5]
    if not artists:
        return {"artists": {}}

    placeholders = ",".join("?" * len(artists))

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()

        # Basic stats
        cursor.execute(
            f"""
            SELECT artist, COUNT(*) as plays,
                   COUNT(DISTINCT track) as unique_tracks,
                   COUNT(DISTINCT album) as unique_albums,
                   MIN(timestamp) as first_seen,
                   MAX(timestamp) as last_seen
            FROM musiclibrary
            WHERE artist IN ({placeholders})
            GROUP BY artist
        """,
            artists,
        )
        basic = {
            row[0]: {
                "plays": row[1],
                "unique_tracks": row[2],
                "unique_albums": row[3],
                "first_seen": row[4],
                "last_seen": row[5],
            }
            for row in cursor.fetchall()
        }

        # Listening time
        cursor.execute(
            f"""
            SELECT m.artist, SUM(td.duration_ms) as total_ms
            FROM musiclibrary m
            JOIN track_durations td ON td.artist = m.artist AND td.track = m.track
            WHERE m.artist IN ({placeholders}) AND td.duration_ms IS NOT NULL
            GROUP BY m.artist
        """,
            artists,
        )
        listening_times = {row[0]: row[1] for row in cursor.fetchall()}

        # Avg track length
        cursor.execute(
            f"""
            SELECT m.artist, AVG(td.duration_ms) as avg_ms
            FROM musiclibrary m
            JOIN track_durations td ON td.artist = m.artist AND td.track = m.track
            WHERE m.artist IN ({placeholders}) AND td.duration_ms IS NOT NULL
            GROUP BY m.artist
        """,
            artists,
        )
        avg_lengths = {row[0]: row[1] for row in cursor.fetchall()}

        # Top track per artist
        cursor.execute(
            f"""
            SELECT artist, track, COUNT(*) as plays
            FROM musiclibrary
            WHERE artist IN ({placeholders})
            GROUP BY artist, track
            ORDER BY plays DESC
        """,
            artists,
        )
        top_tracks: dict[str, tuple[str, int]] = {}
        for row in cursor.fetchall():
            if row[0] not in top_tracks:
                top_tracks[row[0]] = (row[1], row[2])

    result = {}
    for artist in artists:
        if artist not in basic:
            continue
        b = basic[artist]
        total_ms = listening_times.get(artist)
        avg_ms = avg_lengths.get(artist)
        first_dt = datetime.datetime.fromtimestamp(b["first_seen"], tz=datetime.UTC)
        last_dt = datetime.datetime.fromtimestamp(b["last_seen"], tz=datetime.UTC)
        top_track, top_track_plays = top_tracks.get(artist, ("—", 0))
        result[artist] = {
            "plays": b["plays"],
            "unique_tracks": b["unique_tracks"],
            "unique_albums": b["unique_albums"],
            "listening_time": format_listening_time(total_ms) if total_ms else "—",
            "avg_track_length": format_track_duration(int(avg_ms)) if avg_ms else "—",
            "first_seen": first_dt.strftime("%Y-%m-%d"),
            "last_seen": last_dt.strftime("%Y-%m-%d"),
            "top_track": top_track,
            "top_track_plays": top_track_plays,
        }
    return {"artists": result}


@app.get("/api/compare/artist-history")
async def compare_artist_history(artists: list[str] = Query(default=[])):  # noqa: B008
    """Return monthly play counts per artist for the comparison chart."""
    artists = artists[:5]
    if not artists:
        return {"months": [], "data": {}}

    placeholders = ",".join("?" * len(artists))

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT artist, strftime('%Y-%m', timestamp, 'unixepoch') as month, COUNT(*) as plays
            FROM musiclibrary
            WHERE artist IN ({placeholders})
            GROUP BY artist, month
            ORDER BY month
        """,
            artists,
        )
        rows = cursor.fetchall()

    # Build unified month list and per-artist series
    all_months: list[str] = sorted({row[1] for row in rows})
    raw: dict[str, dict[str, int]] = {a: {} for a in artists}
    for artist, month, plays in rows:
        raw[artist][month] = plays

    data = {artist: [raw[artist].get(m, 0) for m in all_months] for artist in artists}
    return {"months": all_months, "data": data}


@app.get("/html/duration/top-songs", response_class=HTMLResponse)
async def duration_top_songs(request: Request, limit: int = 20):
    """Top songs by total time spent listening."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT m.artist, m.track, COUNT(*) as plays, SUM(td.duration_ms) as total_ms
            FROM musiclibrary m
            JOIN track_durations td ON td.artist = m.artist AND td.track = m.track
            WHERE td.duration_ms IS NOT NULL
            GROUP BY m.artist, m.track
            ORDER BY total_ms DESC
            LIMIT ?
        """,
            (limit,),
        )
        items = [
            {
                "artist": row[0],
                "track": row[1],
                "plays": row[2],
                "time": format_listening_time(row[3]),
                "raw_ms": row[3],
            }
            for row in cursor.fetchall()
        ]
    return templates.TemplateResponse(
        request,
        "_duration_top_items.html",
        {"items": items, "item_type": "songs"},
    )


@app.get("/html/duration/top-albums", response_class=HTMLResponse)
async def duration_top_albums(request: Request, limit: int = 20):
    """Top albums by total time spent listening."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT m.artist, m.album, COUNT(*) as plays, SUM(td.duration_ms) as total_ms
            FROM musiclibrary m
            JOIN track_durations td ON td.artist = m.artist AND td.track = m.track
            WHERE td.duration_ms IS NOT NULL AND m.album != ''
            GROUP BY m.artist, m.album
            ORDER BY total_ms DESC
            LIMIT ?
        """,
            (limit,),
        )
        items = [
            {
                "artist": row[0],
                "album": row[1],
                "plays": row[2],
                "time": format_listening_time(row[3]),
                "raw_ms": row[3],
            }
            for row in cursor.fetchall()
        ]
    return templates.TemplateResponse(
        request,
        "_duration_top_items.html",
        {"items": items, "item_type": "albums"},
    )


@app.get("/html/duration/top-artists", response_class=HTMLResponse)
async def duration_top_artists(request: Request, limit: int = 20):
    """Top artists by total time spent listening."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT m.artist, COUNT(*) as plays, SUM(td.duration_ms) as total_ms
            FROM musiclibrary m
            JOIN track_durations td ON td.artist = m.artist AND td.track = m.track
            WHERE td.duration_ms IS NOT NULL
            GROUP BY m.artist
            ORDER BY total_ms DESC
            LIMIT ?
        """,
            (limit,),
        )
        items = [
            {
                "artist": row[0],
                "plays": row[1],
                "time": format_listening_time(row[2]),
                "raw_ms": row[2],
            }
            for row in cursor.fetchall()
        ]
    return templates.TemplateResponse(
        request,
        "_duration_top_items.html",
        {"items": items, "item_type": "artists"},
    )


@app.get("/html/duration/longest-songs", response_class=HTMLResponse)
async def duration_longest_songs(request: Request, limit: int = 20, min_plays: int = 10):
    """Longest songs (by track duration) with at least min_plays plays."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT td.artist, td.track, td.duration_ms, COUNT(*) as plays
            FROM track_durations td
            JOIN musiclibrary m ON m.artist = td.artist AND m.track = td.track
            WHERE td.duration_ms IS NOT NULL
            GROUP BY td.artist, td.track
            HAVING plays >= ?
            ORDER BY td.duration_ms DESC
            LIMIT ?
        """,
            (min_plays, limit),
        )
        items = [
            {
                "artist": row[0],
                "track": row[1],
                "duration": format_track_duration(row[2]),
                "plays": row[3],
            }
            for row in cursor.fetchall()
        ]
    return templates.TemplateResponse(
        request,
        "_duration_song_lengths.html",
        {"items": items, "direction": "longest"},
    )


@app.get("/html/duration/shortest-songs", response_class=HTMLResponse)
async def duration_shortest_songs(request: Request, limit: int = 20, min_plays: int = 10):
    """Shortest songs (by track duration) with at least min_plays plays."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT td.artist, td.track, td.duration_ms, COUNT(*) as plays
            FROM track_durations td
            JOIN musiclibrary m ON m.artist = td.artist AND m.track = td.track
            WHERE td.duration_ms IS NOT NULL
            GROUP BY td.artist, td.track
            HAVING plays >= ?
            ORDER BY td.duration_ms ASC
            LIMIT ?
        """,
            (min_plays, limit),
        )
        items = [
            {
                "artist": row[0],
                "track": row[1],
                "duration": format_track_duration(row[2]),
                "plays": row[3],
            }
            for row in cursor.fetchall()
        ]
    return templates.TemplateResponse(
        request,
        "_duration_song_lengths.html",
        {"items": items, "direction": "shortest"},
    )


@app.get("/api/duration/avg-over-time")
async def duration_avg_over_time():
    """Average song length per month over all time."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT strftime('%Y-%m', timestamp, 'unixepoch') as month,
                   AVG(td.duration_ms) as avg_ms,
                   COUNT(*) as plays
            FROM musiclibrary m
            JOIN track_durations td ON td.artist = m.artist AND td.track = m.track
            WHERE td.duration_ms IS NOT NULL
            GROUP BY month
            ORDER BY month
        """
        )
        rows = cursor.fetchall()
    months = [row[0] for row in rows]
    avg_seconds = [round(row[1] / 1000) for row in rows]
    return {"months": months, "avg_seconds": avg_seconds}


@app.get("/api/duration/histogram")
async def duration_histogram():
    """Distribution of song durations (bucketed by minute) across played library."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT (duration_ms / 60000) as minute_bucket,
                   COUNT(*) as unique_songs,
                   SUM(plays) as total_plays
            FROM (
                SELECT m.artist, m.track, td.duration_ms, COUNT(*) as plays
                FROM musiclibrary m
                JOIN track_durations td ON td.artist = m.artist AND td.track = m.track
                WHERE td.duration_ms IS NOT NULL
                GROUP BY m.artist, m.track
            ) AS sub
            GROUP BY minute_bucket
            ORDER BY minute_bucket
        """
        )
        rows = cursor.fetchall()

    # Cap at 15 min, lump remainder into "15m+" bucket
    cap = 15
    bucketed: dict[int, tuple[int, int]] = {}
    overflow_songs = 0
    overflow_plays = 0
    for bucket, songs, plays in rows:
        if bucket >= cap:
            overflow_songs += songs
            overflow_plays += plays
        else:
            bucketed[bucket] = (songs, plays)

    labels = [f"{i}-{i+1}m" for i in range(cap)]
    unique_songs = [bucketed.get(i, (0, 0))[0] for i in range(cap)]
    total_plays = [bucketed.get(i, (0, 0))[1] for i in range(cap)]
    if overflow_songs:
        labels.append(f"{cap}m+")
        unique_songs.append(overflow_songs)
        total_plays.append(overflow_plays)

    return {"buckets": labels, "unique_songs": unique_songs, "total_plays": total_plays}


@app.get("/html/duration/artists-by-length", response_class=HTMLResponse)
async def duration_artists_by_length(
    request: Request, limit: int = 20, min_plays: int = 50
):
    """Artists ranked by average track length, with at least min_plays total plays."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT m.artist, AVG(td.duration_ms) as avg_ms, COUNT(DISTINCT m.track) as unique_tracks
            FROM musiclibrary m
            JOIN track_durations td ON td.artist = m.artist AND td.track = m.track
            WHERE td.duration_ms IS NOT NULL
            GROUP BY m.artist
            HAVING COUNT(*) >= ?
            ORDER BY avg_ms DESC
            LIMIT ?
        """,
            (min_plays, limit),
        )
        items = [
            {
                "artist": row[0],
                "avg_duration": format_track_duration(int(row[1])),
                "unique_tracks": row[2],
            }
            for row in cursor.fetchall()
        ]
    return templates.TemplateResponse(
        request,
        "_duration_artists_length.html",
        {"items": items},
    )


@app.get("/api/yearly/time-patterns-duration")
async def yearly_time_patterns_duration(year: int):
    """Get listening time in minutes by hour and day of week for a specific year."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT strftime('%H', timestamp, 'unixepoch') as hour,
                   SUM(td.duration_ms) as total_ms
            FROM musiclibrary m
            JOIN track_durations td ON td.artist = m.artist AND td.track = m.track
            WHERE td.duration_ms IS NOT NULL
              AND strftime('%Y', timestamp, 'unixepoch') = ?
            GROUP BY hour
            ORDER BY hour
        """,
            (str(year),),
        )
        hourly_raw = {int(row[0]): row[1] / 60_000 for row in cursor.fetchall()}
        hourly_data = [round(hourly_raw.get(h, 0), 1) for h in range(24)]

        cursor.execute(
            """
            SELECT strftime('%w', timestamp, 'unixepoch') as dow,
                   SUM(td.duration_ms) as total_ms
            FROM musiclibrary m
            JOIN track_durations td ON td.artist = m.artist AND td.track = m.track
            WHERE td.duration_ms IS NOT NULL
              AND strftime('%Y', timestamp, 'unixepoch') = ?
            GROUP BY dow
            ORDER BY dow
        """,
            (str(year),),
        )
        weekly_raw = {int(row[0]): row[1] / 60_000 for row in cursor.fetchall()}
        # strftime('%w'): 0=Sunday … 6=Saturday; reorder to Mon–Sun
        day_order = [1, 2, 3, 4, 5, 6, 0]
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        weekly_data = [round(weekly_raw.get(d, 0), 1) for d in day_order]

    return {"hourly": hourly_data, "weekly": weekly_data, "day_names": day_names}


@app.get("/api/yearly/time-patterns")
async def yearly_time_patterns(year: int):
    """Get listening patterns by hour and day of week for a specific year."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()

        # Hour of day pattern (0-23)
        cursor.execute(
            """
            SELECT strftime('%H', timestamp, 'unixepoch') as hour, COUNT(*) as plays
            FROM musiclibrary
            WHERE strftime('%Y', timestamp, 'unixepoch') = ?
            GROUP BY hour
            ORDER BY hour
        """,
            (str(year),),
        )
        hourly = {int(row[0]): row[1] for row in cursor.fetchall()}
        # Fill in missing hours with 0
        hourly_data = [hourly.get(h, 0) for h in range(24)]

        # Day of week pattern (0=Monday, 6=Sunday)
        cursor.execute(
            """
            SELECT strftime('%w', timestamp, 'unixepoch') as dow, COUNT(*) as plays
            FROM musiclibrary
            WHERE strftime('%Y', timestamp, 'unixepoch') = ?
            GROUP BY dow
            ORDER BY dow
        """,
            (str(year),),
        )
        weekly = {int(row[0]): row[1] for row in cursor.fetchall()}
        # SQLite %w: 0=Sunday, 1=Monday, ..., 6=Saturday
        # Convert to 0=Monday format
        day_names = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]
        weekly_data = [
            weekly.get(1, 0),  # Monday
            weekly.get(2, 0),  # Tuesday
            weekly.get(3, 0),  # Wednesday
            weekly.get(4, 0),  # Thursday
            weekly.get(5, 0),  # Friday
            weekly.get(6, 0),  # Saturday
            weekly.get(0, 0),  # Sunday
        ]

    return {
        "hourly": hourly_data,
        "weekly": weekly_data,
        "day_names": day_names,
    }


@app.get("/api/yearly/evolution")
async def yearly_evolution(
    year: int, item_type: str = "artists", top_n: int = 5
) -> dict:
    """Get evolution of items that appeared in monthly top N throughout the year.

    Instead of tracking the top N for the entire year, this finds all items
    that were in the top N of ANY month, then shows their evolution.

    Parameters
    ----------
    year : int
        Year to analyze
    item_type : str
        One of: 'artists', 'albums', 'songs'
    top_n : int
        Number of top items per month to track (default: 5)

    Returns
    -------
    dict
        Contains dates, item names, and their play counts over time
    """
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()

        # Generate all months in the year
        all_months = [f"{year}-{month:02d}" for month in range(1, 13)]

        # Collect all unique items that appeared in top N of any month
        all_top_items = set()

        for month_str in all_months:
            if item_type == "artists":
                cursor.execute(
                    """
                    SELECT artist, COUNT(*) as plays
                    FROM musiclibrary
                    WHERE strftime('%Y-%m', timestamp, 'unixepoch') = ?
                    GROUP BY artist
                    ORDER BY plays DESC
                    LIMIT ?
                """,
                    (month_str, top_n),
                )
                month_tops = [row[0] for row in cursor.fetchall()]
            elif item_type == "albums":
                cursor.execute(
                    """
                    SELECT artist || ' - ' || album as full_album, COUNT(*) as plays
                    FROM musiclibrary
                    WHERE strftime('%Y-%m', timestamp, 'unixepoch') = ?
                        AND album != ''
                    GROUP BY artist, album
                    ORDER BY plays DESC
                    LIMIT ?
                """,
                    (month_str, top_n),
                )
                month_tops = [row[0] for row in cursor.fetchall()]
            else:  # songs
                cursor.execute(
                    """
                    SELECT artist || ' - ' || track as full_track, COUNT(*) as plays
                    FROM musiclibrary
                    WHERE strftime('%Y-%m', timestamp, 'unixepoch') = ?
                    GROUP BY artist, track
                    ORDER BY plays DESC
                    LIMIT ?
                """,
                    (month_str, top_n),
                )
                month_tops = [row[0] for row in cursor.fetchall()]

            all_top_items.update(month_tops)

        if not all_top_items:
            return {"dates": [], "items": [], "data": []}

        # Get monthly counts for each top item throughout the year
        evolution_data = {}

        for item in all_top_items:
            if item_type == "artists":
                cursor.execute(
                    """
                    SELECT strftime('%Y-%m', timestamp, 'unixepoch') as month, COUNT(*) as plays
                    FROM musiclibrary
                    WHERE strftime('%Y', timestamp, 'unixepoch') = ?
                        AND artist = ?
                    GROUP BY month
                    ORDER BY month
                """,
                    (str(year), item),
                )
            elif item_type == "albums":
                # Split back the combined name (format: "Artist - Album")
                parts = item.split(" - ", 1)
                expected_parts = 2
                if len(parts) == expected_parts:
                    artist, album = parts
                    cursor.execute(
                        """
                        SELECT strftime('%Y-%m', timestamp, 'unixepoch') as month, COUNT(*) as plays
                        FROM musiclibrary
                        WHERE strftime('%Y', timestamp, 'unixepoch') = ?
                            AND artist = ?
                            AND album = ?
                        GROUP BY month
                        ORDER BY month
                    """,
                        (str(year), artist, album),
                    )
                else:
                    continue
            else:  # songs
                # Split back the combined name (format: "Artist - Track")
                parts = item.split(" - ", 1)
                expected_parts = 2
                if len(parts) == expected_parts:
                    artist, track = parts
                    cursor.execute(
                        """
                        SELECT strftime('%Y-%m', timestamp, 'unixepoch') as month, COUNT(*) as plays
                        FROM musiclibrary
                        WHERE strftime('%Y', timestamp, 'unixepoch') = ?
                            AND artist = ?
                            AND track = ?
                        GROUP BY month
                        ORDER BY month
                    """,
                        (str(year), artist, track),
                    )
                else:
                    continue

            monthly_counts = {row[0]: row[1] for row in cursor.fetchall()}
            evolution_data[item] = monthly_counts

    # Generate all months in the year
    all_months = []
    for month in range(1, 13):
        all_months.append(f"{year}-{month:02d}")

    # Get monthly data for each item
    result_data = {}

    for item in all_top_items:
        monthly_data = [evolution_data[item].get(month, 0) for month in all_months]
        result_data[item] = monthly_data

    return {
        "dates": all_months,
        "items": list(all_top_items),
        "data": result_data,
    }


def _aggregate_genres(
    rows: list[tuple[str, int, str]], top_n: int = 20
) -> list[dict[str, object]]:
    """Aggregate genre tags weighted by play count.

    Parameters
    ----------
    rows : list[tuple[str, int, str]]
        Rows of (artist, plays, tags_json).
    top_n : int
        Number of top genres to return.

    Returns
    -------
    list[dict[str, object]]
        Dicts of {"genre": str, "score": float} sorted descending.
    """
    totals: dict[str, float] = {}
    for _artist, plays, tags_json in rows:
        for entry in json.loads(tags_json):
            tag = str(entry["tag"]).lower()
            weight = int(entry.get("weight", 1))
            totals[tag] = totals.get(tag, 0.0) + plays * (weight / 100)
    sorted_tags = sorted(totals.items(), key=lambda x: x[1], reverse=True)
    return [{"genre": tag, "score": round(score, 1)} for tag, score in sorted_tags[:top_n]]


@app.get("/genre-stats", response_class=HTMLResponse)
async def genre_stats_page(request: Request):
    """Genre statistics page."""
    with sqlite3.connect(DB_NAME) as conn:
        years = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT strftime('%Y', timestamp, 'unixepoch') as year FROM musiclibrary ORDER BY year DESC"
            ).fetchall()
        ]
    return templates.TemplateResponse(
        request, "genre_stats.html", {"years": years}
    )


@app.get("/html/genre/top-genres", response_class=HTMLResponse)
async def genre_top_genres(request: Request, limit: int = 20):
    """Top genres overall as HTML fragment."""
    with sqlite3.connect(DB_NAME) as conn:
        rows = conn.execute(
            """SELECT m.artist, COUNT(*) as plays, ag.tags
               FROM musiclibrary m
               JOIN artist_genres ag ON ag.artist = m.artist
               WHERE ag.tags != '[]'
               GROUP BY m.artist""",
        ).fetchall()
    genres = _aggregate_genres(rows, top_n=limit)
    return templates.TemplateResponse(
        request, "_genre_list.html", {"genres": genres}
    )


@app.get("/html/genre/top-genres-year", response_class=HTMLResponse)
async def genre_top_genres_year(request: Request, year: str, limit: int = 20):
    """Top genres for a specific year as HTML fragment."""
    with sqlite3.connect(DB_NAME) as conn:
        rows = conn.execute(
            """SELECT m.artist, COUNT(*) as plays, ag.tags
               FROM musiclibrary m
               JOIN artist_genres ag ON ag.artist = m.artist
               WHERE ag.tags != '[]'
                 AND strftime('%Y', m.timestamp, 'unixepoch') = ?
               GROUP BY m.artist""",
            (year,),
        ).fetchall()
    genres = _aggregate_genres(rows, top_n=limit)
    return templates.TemplateResponse(
        request, "_genre_list.html", {"genres": genres}
    )


@app.get("/api/genre/evolution")
async def genre_evolution():
    """Genre distribution over years for stacked area chart."""
    with sqlite3.connect(DB_NAME) as conn:
        rows = conn.execute(
            """SELECT strftime('%Y', m.timestamp, 'unixepoch') as year,
                      m.artist, COUNT(*) as plays, ag.tags
               FROM musiclibrary m
               JOIN artist_genres ag ON ag.artist = m.artist
               WHERE ag.tags != '[]'
               GROUP BY year, m.artist
               ORDER BY year""",
        ).fetchall()

    # Aggregate per year
    year_totals: dict[str, dict[str, float]] = {}
    for year, _artist, plays, tags_json in rows:
        if year not in year_totals:
            year_totals[year] = {}
        for entry in json.loads(tags_json):
            tag = str(entry["tag"]).lower()
            weight = int(entry.get("weight", 1))
            year_totals[year][tag] = year_totals[year].get(tag, 0.0) + plays * (weight / 100)

    # Find top 8 genres overall
    overall: dict[str, float] = {}
    for ytags in year_totals.values():
        for tag, score in ytags.items():
            overall[tag] = overall.get(tag, 0.0) + score
    top_genres = [g for g, _ in sorted(overall.items(), key=lambda x: x[1], reverse=True)[:8]]

    years = sorted(year_totals.keys())
    series = []
    for genre in top_genres:
        raw = [year_totals[y].get(genre, 0.0) for y in years]
        year_sums = [sum(year_totals[y].values()) for y in years]
        pct = [round(raw[i] / year_sums[i] * 100, 1) if year_sums[i] else 0.0 for i in range(len(years))]
        series.append({"genre": genre, "data": pct})

    return {"years": years, "series": series}


@app.get("/genre/{genre_name}", response_class=HTMLResponse)
async def genre_detail(request: Request, genre_name: str):
    """Detail page for a specific genre."""
    with sqlite3.connect(DB_NAME) as conn:
        rows = conn.execute(
            "SELECT artist, tags FROM artist_genres WHERE tags != '[]'"
        ).fetchall()

    # Find artists tagged with this genre and their tag weight
    genre_weights: dict[str, int] = {}
    for artist, tags_json in rows:
        for entry in json.loads(tags_json):
            if str(entry["tag"]).lower() == genre_name.lower():
                genre_weights[artist] = int(entry.get("weight", 1))
                break

    if not genre_weights:
        raise HTTPException(status_code=404, detail=f"Genre '{genre_name}' not found")

    artist_list = list(genre_weights.keys())
    placeholders = ",".join("?" * len(artist_list))

    with sqlite3.connect(DB_NAME) as conn:
        play_rows = conn.execute(
            f"SELECT artist, COUNT(*) as plays FROM musiclibrary WHERE artist IN ({placeholders}) GROUP BY artist",
            artist_list,
        ).fetchall()
        play_counts = {r[0]: r[1] for r in play_rows}

        top_tracks_rows = conn.execute(
            f"""SELECT artist, track, COUNT(*) as plays
                FROM musiclibrary WHERE artist IN ({placeholders})
                GROUP BY artist, track ORDER BY plays DESC LIMIT 20""",
            artist_list,
        ).fetchall()

        top_albums_rows = conn.execute(
            f"""SELECT artist, album, COUNT(*) as plays
                FROM musiclibrary WHERE artist IN ({placeholders}) AND album != ''
                GROUP BY artist, album ORDER BY plays DESC LIMIT 20""",
            artist_list,
        ).fetchall()

        monthly_rows = conn.execute(
            f"""SELECT strftime('%Y-%m', timestamp, 'unixepoch') as month, COUNT(*) as plays
                FROM musiclibrary WHERE artist IN ({placeholders})
                GROUP BY month ORDER BY month""",
            artist_list,
        ).fetchall()

    top_artists = sorted(
        [
            {
                "artist": a,
                "plays": play_counts.get(a, 0),
                "weighted": round(play_counts.get(a, 0) * genre_weights[a] / 100),
            }
            for a in genre_weights
            if play_counts.get(a, 0) > 0
        ],
        key=lambda x: x["weighted"],
        reverse=True,
    )[:20]

    return templates.TemplateResponse(
        request,
        "genre.html",
        {
            "genre": genre_name,
            "total_plays": sum(play_counts.values()),
            "total_artists": len(top_artists),
            "top_artists": top_artists,
            "top_tracks": [{"artist": r[0], "track": r[1], "plays": r[2]} for r in top_tracks_rows],
            "top_albums": [{"artist": r[0], "album": r[1], "plays": r[2]} for r in top_albums_rows],
            "monthly": [{"month": r[0], "plays": r[1]} for r in monthly_rows],
        },
    )


@app.get("/discovery", response_class=HTMLResponse)
async def discovery_page(request: Request):
    """Music discovery timeline — artists sorted by first scrobble date."""
    with sqlite3.connect(DB_NAME) as conn:
        rows = conn.execute(
            "SELECT artist, MIN(timestamp) as first_heard FROM musiclibrary GROUP BY artist ORDER BY first_heard ASC"
        ).fetchall()

    years_data: dict[str, list[dict[str, str]]] = {}
    for artist, ts in rows:
        dt = datetime.datetime.fromtimestamp(ts)
        year = str(dt.year)
        if year not in years_data:
            years_data[year] = []
        years_data[year].append({"artist": artist, "date": dt.strftime("%-d %b")})

    # Reverse so most recent year is first
    ordered = [(y, years_data[y]) for y in sorted(years_data.keys(), reverse=True)]
    return templates.TemplateResponse(
        request, "discovery.html", {"years": ordered}
    )


def main():
    """Run the application server."""
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
