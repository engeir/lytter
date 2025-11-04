"""Simple FastAPI application for Last.fm stats."""

import datetime
import json
import os
import sqlite3
from collections import Counter, OrderedDict

import pylast
import requests
from dotenv import load_dotenv

# Note: These imports may show errors in the editor but will work when dependencies are installed
try:
    import pandas as pd
    import plotly.express as px
    import plotly.utils
    from fastapi import FastAPI, Form, HTTPException, Request
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
except ImportError as e:
    print(f"Import error: {e}")
    print("Please install dependencies with: uv sync")

load_dotenv()

# Configuration
API_KEY = os.environ.get("API_KEY")
API_SECRET = os.environ.get("API_SECRET")
USER_NAME = os.environ.get("USER_NAME")
PASSWORD = os.environ.get("PASSWORD")
PASSWORD_HASH = pylast.md5(PASSWORD) if PASSWORD else None
UPDATE_PASSWORD = os.environ.get("UPDATE_PASSWORD")

# pylast network
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
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


# Database helper functions
def get_db_connection():
    """Get SQLite database connection."""
    return sqlite3.connect("reflex.db")


def init_db():
    """Initialize database with table if it doesn't exist."""
    conn = get_db_connection()
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
    conn.commit()
    conn.close()


# Initialize database on startup
init_db()


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
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(timestamp) FROM musiclibrary")
        result = cursor.fetchone()[0]
        conn.close()
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
                import datetime

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

        conn = get_db_connection()
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
                if "@attr" in scrobble and scrobble["@attr"]["nowplaying"] == "true":
                    continue

                scrobble_timestamp = int(scrobble["date"]["uts"])

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
                        consecutive_old_scrobbles >= 50
                        and not full
                        and latest_timestamp > 0
                        and scrobble_timestamp <= latest_timestamp
                    ):
                        print(
                            f"\nFound {consecutive_old_scrobbles} consecutive existing scrobbles beyond latest timestamp, stopping"
                        )
                        conn.close()
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
                print(f"\nNo new scrobbles found on page {page_}, likely up to date")
                break

        conn.close()
        print(f"\nUpdate complete! Added {new_scrobbles_count} new scrobbles.")
        return new_scrobbles_count


class CurrentStats:
    """Show stats about a given artist."""

    def listening_history_db(self, artist: str):
        """Get the artist listening history as a cumulative line plot."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT timestamp FROM musiclibrary WHERE artist = ? ORDER BY timestamp",
            (artist,),
        )
        timestamps = [row[0] for row in cursor.fetchall()]
        conn.close()

        dates = [datetime.datetime.fromtimestamp(int(ts)) for ts in timestamps]
        counts = list(range(1, len(dates) + 1))

        fig = px.line(x=dates, y=counts, title="Listening history")
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
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT track FROM musiclibrary WHERE artist = ?", (artist,))
        tracks = [row[0] for row in cursor.fetchall()]
        conn.close()

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
    """Main dashboard page."""
    # Get basic stats
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM musiclibrary")
    total_scrobbles = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT artist) FROM musiclibrary")
    unique_artists = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT track) FROM musiclibrary")
    unique_tracks = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT album) FROM musiclibrary WHERE album != ''")
    unique_albums = cursor.fetchone()[0]

    conn.close()

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
        "index.html",
        {
            "request": request,
            "total_scrobbles": total_scrobbles,
            "unique_artists": unique_artists,
            "unique_tracks": unique_tracks,
            "unique_albums": unique_albums,
            "current_track": current_track,
        },
    )


@app.get("/artist/{artist_name}", response_class=HTMLResponse)
async def artist_stats(request: Request, artist_name: str):
    """Artist statistics page."""
    stats = CurrentStats()

    # Get listening history (already returns plain dict)
    history_json = json.dumps(stats.listening_history_db(artist_name))

    # Get top songs (already returns plain dict)
    songs_json = json.dumps(stats.top_songs(artist_name))

    # Get basic artist stats
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM musiclibrary WHERE artist = ?", (artist_name,))
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

    conn.close()

    return templates.TemplateResponse(
        "artist.html",
        {
            "request": request,
            "artist_name": artist_name,
            "total_plays": total_plays,
            "unique_tracks": unique_tracks,
            "unique_albums": unique_albums,
            "history_chart": history_json,
            "songs_chart": songs_json,
        },
    )


@app.get("/top-artists")
async def top_artists():
    """Get top artists data."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT artist, COUNT(*) as plays FROM musiclibrary GROUP BY artist ORDER BY plays DESC LIMIT 50"
    )
    result = cursor.fetchall()
    conn.close()

    artists = [{"artist": row[0], "plays": row[1]} for row in result]
    return {"artists": artists}


@app.get("/charts/listening-timeline")
async def listening_timeline():
    """Generate listening timeline chart."""
    conn = get_db_connection()
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
    conn.close()

    df = pd.DataFrame(result, columns=["date", "plays"])
    df["date"] = pd.to_datetime(df["date"])

    fig = px.line(
        df, x="date", y="plays", title="Daily Listening Activity (Last 365 Days)"
    )

    # Calculate initial view range (last 30 days)
    if len(df) > 0:
        max_date = df["date"].max()
        min_date = df["date"].min()
        initial_end = max_date
        initial_start = max_date - pd.Timedelta(days=30)
        # Make sure initial_start is not before the min_date
        initial_start = max(initial_start, min_date)
    else:
        initial_start = initial_end = None

    fig.update_layout(
        xaxis_title="Date",
        yaxis_title="Number of Scrobbles",
        paper_bgcolor="#161b22",
        plot_bgcolor="#161b22",
        font=dict(color="#f0f6fc"),
        xaxis=dict(
            gridcolor="#30363d",
            color="#f0f6fc",
            range=[initial_start, initial_end] if initial_start else None,
            rangeslider=dict(
                visible=True,
                bgcolor="#0d1117",
                bordercolor="#30363d",
                borderwidth=1,
            ),
            rangeselector=dict(
                buttons=list(
                    [
                        dict(count=7, label="1w", step="day", stepmode="backward"),
                        dict(count=14, label="2w", step="day", stepmode="backward"),
                        dict(count=1, label="1m", step="month", stepmode="backward"),
                        dict(count=3, label="3m", step="month", stepmode="backward"),
                        dict(count=6, label="6m", step="month", stepmode="backward"),
                        dict(step="all", label="All"),
                    ]
                ),
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

    # Convert to plain dict without binary encoding
    fig_dict = fig.to_dict()
    # Force y and x values to be plain lists
    fig_dict["data"][0]["y"] = df["plays"].tolist()
    fig_dict["data"][0]["x"] = df["date"].dt.strftime("%Y-%m-%dT%H:%M:%S").tolist()

    return fig_dict


@app.get("/recent-stats")
async def recent_stats():
    """Get top artists, albums, and songs from past week and month."""
    conn = get_db_connection()
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
    week_artists = [{"artist": row[0], "plays": row[1]} for row in cursor.fetchall()]

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
    month_artists = [{"artist": row[0], "plays": row[1]} for row in cursor.fetchall()]

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

    conn.close()

    return {
        "week_artists": week_artists,
        "week_albums": week_albums,
        "week_songs": week_songs,
        "month_artists": month_artists,
        "month_albums": month_albums,
        "month_songs": month_songs,
    }


# Removed admin panel and web-based updates
# Database updates should be handled via cron jobs or background tasks


@app.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request):
    """Statistics page."""
    return templates.TemplateResponse("stats.html", {"request": request})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
