# Front Page Redesign — "Recently" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or superpowers:executing-plans
> to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the front page into a recency-focused view, move all-time analytics
to `/all-time`, and add a responsive mobile navbar.

**Architecture:** Backend changes first (new helpers + endpoints), then template
changes, then navbar. Each task is independently committable. No new dependencies except
`httpx` for tests.

**Tech Stack:** FastAPI, Jinja2, HTMX, Bootstrap 5, SQLite, Plotly, pytest + httpx
(TestClient)

---

## File Map

| File                                      | Action | What changes                                                                                                                                                     |
| ----------------------------------------- | ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/lytter/app.py`                       | Modify | Add `_relative_time`, `_get_dashboard_stats`; new `/html/recent-plays`; extend `/charts/listening-timeline` with `range` param; update `index()` and `alltime()` |
| `src/lytter/templates/_recent_plays.html` | Create | HTMX fragment: 30-row recent scrobbles list                                                                                                                      |
| `src/lytter/templates/index.html`         | Modify | Remove stat cards, timeline chart, streaks chart, top-tabs; add Recent Plays card                                                                                |
| `src/lytter/templates/alltime.html`       | Modify | Add stat cards row, timeline chart section, streaks chart section                                                                                                |
| `src/lytter/templates/base.html`          | Modify | Bootstrap 5 collapsible navbar with hamburger                                                                                                                    |
| `src/lytter/static/styles.css`            | Modify | Add `.recent-plays-*` styles                                                                                                                                     |
| `pyproject.toml`                          | Modify | Add `httpx` to dev deps                                                                                                                                          |
| `tests/conftest.py`                       | Create | Shared test DB fixture                                                                                                                                           |
| `tests/test_helpers.py`                   | Create | Unit tests for `_relative_time` and `_get_dashboard_stats`                                                                                                       |
| `tests/test_endpoints.py`                 | Create | Integration tests for `/html/recent-plays` and `/charts/listening-timeline`                                                                                      |

---

## Task 1: Add httpx dev dependency + test infrastructure

**Files:**

- Modify: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Add httpx to dev dependencies**

In `pyproject.toml`, add `"httpx>=0.27.0"` to the `[dependency-groups] dev` list:

```toml
dev = [
  "httpx>=0.27.0",
  "types-requests>=2.32.0.20240914",
  # ... rest unchanged
]
```

- [ ] **Step 2: Install the new dependency**

```bash
uv sync
```

Expected: resolves without error, httpx appears in lock file.

- [ ] **Step 3: Create tests package**

Create `tests/__init__.py` as an empty file.

- [ ] **Step 4: Create conftest.py**

Create `tests/conftest.py`:

```python
import sqlite3
import time

import pytest


@pytest.fixture()
def test_db(tmp_path, monkeypatch):
    """In-memory SQLite DB with schema + sample data, DB_NAME monkeypatched."""
    import lytter.app as app_module

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
    from fastapi.testclient import TestClient
    from lytter.app import app

    return TestClient(app)
```

- [ ] **Step 5: Verify pytest discovers tests**

```bash
uv run pytest tests/ --collect-only
```

Expected: `no tests ran` (0 tests collected, no errors).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml tests/__init__.py tests/conftest.py
git commit -m "test: add httpx dev dep and test infrastructure"
```

---

## Task 2: Extract `_get_dashboard_stats` helper

**Files:**

- Modify: `src/lytter/app.py` (around line 977 `index()`, and near `_compute_streaks` at
  line 560)
- Create: `tests/test_helpers.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_helpers.py`:

```python
import sqlite3
import time

import pytest


def test_get_dashboard_stats_counts(test_db):
    import lytter.app as app_module

    with sqlite3.connect(test_db) as conn:
        stats = app_module._get_dashboard_stats(conn)

    assert stats["total_scrobbles"] == 3
    assert stats["unique_artists"] == 2
    assert stats["unique_tracks"] == 3
    assert stats["unique_albums"] == 2


def test_get_dashboard_stats_listening_time(test_db):
    import lytter.app as app_module

    with sqlite3.connect(test_db) as conn:
        stats = app_module._get_dashboard_stats(conn)

    # Only Radiohead/Paranoid Android has a duration (383000ms, played 1x)
    assert stats["total_listening_time"] is not None
    assert stats["listening_time_known_tracks"] == 1
    assert stats["listening_time_total_tracks"] == 3


def test_get_dashboard_stats_streaks(test_db):
    import lytter.app as app_module

    with sqlite3.connect(test_db) as conn:
        stats = app_module._get_dashboard_stats(conn)

    assert isinstance(stats["current_streak"], int)
    assert isinstance(stats["longest_streak"], int)
    assert stats["current_streak"] >= 0
    assert stats["longest_streak"] >= 0
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
uv run pytest tests/test_helpers.py -v
```

Expected: `AttributeError: module 'lytter.app' has no attribute '_get_dashboard_stats'`

- [ ] **Step 3: Add `_get_dashboard_stats` to `app.py`**

Add this function right after the `_compute_streaks` function (after line ~599):

```python
def _get_dashboard_stats(conn: sqlite3.Connection) -> dict:
    """Query all dashboard summary statistics from an open DB connection.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.

    Returns
    -------
    dict
        Keys: total_scrobbles, unique_artists, unique_tracks, unique_albums,
        total_listening_time, listening_time_known_tracks,
        listening_time_total_tracks, current_streak, longest_streak.
    """
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

    return {
        "total_scrobbles": total_scrobbles,
        "unique_artists": unique_artists,
        "unique_tracks": unique_tracks,
        "unique_albums": unique_albums,
        "total_listening_time": total_listening_time,
        "listening_time_known_tracks": known_track_count,
        "listening_time_total_tracks": total_track_count,
        "current_streak": current_streak,
        "longest_streak": longest_streak,
    }
```

- [ ] **Step 4: Replace stat queries in `index()` with the helper**

In `index()` (around line 977), replace the entire
`with sqlite3.connect(DB_NAME) as conn:` block (lines 981–1006) with:

```python
    with sqlite3.connect(DB_NAME) as conn:
        stats = _get_dashboard_stats(conn)
```

Then update the `templates.TemplateResponse` call to unpack stats:

```python
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            **stats,
            "current_track": current_track,
        },
    )
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_helpers.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 6: Run quality checks**

```bash
hk check
```

Fix any issues before committing.

- [ ] **Step 7: Commit**

```bash
git add src/lytter/app.py tests/test_helpers.py
git commit -m "refactor: extract _get_dashboard_stats helper"
```

---

## Task 3: Add `_relative_time` helper + `/html/recent-plays` endpoint

**Files:**

- Modify: `src/lytter/app.py`
- Create: `src/lytter/templates/_recent_plays.html`
- Modify: `src/lytter/static/styles.css`
- Modify: `tests/test_helpers.py`
- Create: `tests/test_endpoints.py`

- [ ] **Step 1: Write failing tests for `_relative_time`**

Append to `tests/test_helpers.py`:

```python
def test_relative_time_just_now():
    import time

    import lytter.app as app_module

    ts = int(time.time()) - 10
    assert app_module._relative_time(ts) == "just now"


def test_relative_time_minutes():
    import time

    import lytter.app as app_module

    ts = int(time.time()) - 300  # 5 minutes ago
    assert app_module._relative_time(ts) == "5m ago"


def test_relative_time_hours():
    import time

    import lytter.app as app_module

    ts = int(time.time()) - 7200  # 2 hours ago
    assert app_module._relative_time(ts) == "2h ago"


def test_relative_time_days():
    import time

    import lytter.app as app_module

    ts = int(time.time()) - 172800  # 2 days ago
    assert app_module._relative_time(ts) == "2d ago"
```

- [ ] **Step 2: Write failing endpoint test**

Create `tests/test_endpoints.py`:

```python
def test_recent_plays_returns_html(client):
    response = client.get("/html/recent-plays")
    assert response.status_code == 200
    assert "Paranoid Android" in response.text
    assert "Radiohead" in response.text
    assert "ago" in response.text


def test_recent_plays_is_ordered_newest_first(client):
    response = client.get("/html/recent-plays")
    assert response.status_code == 200
    # "Paranoid Android" (most recent) should appear before "Blood in the Cut"
    idx_paranoid = response.text.index("Paranoid Android")
    idx_blood = response.text.index("Blood in the Cut")
    assert idx_paranoid < idx_blood
```

- [ ] **Step 3: Run tests to confirm they fail**

```bash
uv run pytest tests/test_helpers.py tests/test_endpoints.py -v
```

Expected: `_relative_time` and `/html/recent-plays` tests fail.

- [ ] **Step 4: Add `_relative_time` to `app.py`**

Add right after the `_get_dashboard_stats` function:

```python
def _relative_time(ts: int) -> str:
    """Return a human-readable relative time string for a Unix timestamp.

    Parameters
    ----------
    ts : int
        Unix timestamp (seconds).

    Returns
    -------
    str
        E.g. "just now", "5m ago", "3h ago", "2d ago".
    """
    import time

    delta = int(time.time()) - ts
    if delta < 60:  # noqa: PLR2004
        return "just now"
    if delta < 3600:  # noqa: PLR2004
        return f"{delta // 60}m ago"
    if delta < 86400:  # noqa: PLR2004
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"
```

- [ ] **Step 5: Add `/html/recent-plays` endpoint to `app.py`**

Add after the `/html/recent-favorites` endpoint (around line 1732):

```python
@app.get("/html/recent-plays", response_class=HTMLResponse)
async def recent_plays_html(request: Request):
    """Get last 30 scrobbles as an HTML fragment for HTMX."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT artist, track, timestamp
            FROM musiclibrary
            ORDER BY timestamp DESC
            LIMIT 30
        """)
        rows = cursor.fetchall()
    plays = [
        {
            "artist": row[0],
            "track": row[1],
            "relative_time": _relative_time(row[2]),
        }
        for row in rows
    ]
    return templates.TemplateResponse(
        request, "_recent_plays.html", {"plays": plays}
    )
```

- [ ] **Step 6: Create `_recent_plays.html` template**

Create `src/lytter/templates/_recent_plays.html`:

```html
{# HTML Fragment for Recent Plays - Loaded via HTMX #} {% from 'macros.html' import
loading_spinner %}
<div class="recent-plays-container">
  {% for play in plays %}
  <div class="recent-plays-row">
    <span class="recent-plays-title">
      <a
        href="/song/{{ play.artist|urlencode }}/{{ play.track|urlencode }}"
        class="recent-plays-track"
        >{{ play.track }}</a
      >
      <span class="recent-plays-sep">·</span>
      <a href="/artist/{{ play.artist|urlencode }}" class="recent-plays-artist"
        >{{ play.artist }}</a
      >
    </span>
    <span class="recent-plays-time">{{ play.relative_time }}</span>
  </div>
  {% endfor %}
  <div class="recent-plays-fade"></div>
</div>
```

- [ ] **Step 7: Add CSS to `styles.css`**

Append to `src/lytter/static/styles.css`:

```css
/* ===== Recent Plays List ===== */
.recent-plays-container {
  position: relative;
  max-height: 320px;
  overflow: hidden;
}

.recent-plays-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 5px 0;
  border-bottom: 1px solid var(--border-color);
  font-size: 0.875rem;
  gap: 8px;
}

.recent-plays-track {
  color: var(--text-primary);
  text-decoration: none;
  font-weight: 500;
}

.recent-plays-track:hover {
  color: var(--accent-blue);
}

.recent-plays-sep {
  color: var(--text-secondary);
  margin: 0 4px;
}

.recent-plays-artist {
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 0.85rem;
}

.recent-plays-artist:hover {
  color: var(--accent-blue);
}

.recent-plays-time {
  color: var(--text-secondary);
  font-size: 0.78rem;
  white-space: nowrap;
  flex-shrink: 0;
}

.recent-plays-fade {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 80px;
  background: linear-gradient(transparent, var(--bg-secondary));
  pointer-events: none;
}
```

- [ ] **Step 8: Run tests**

```bash
uv run pytest tests/test_helpers.py tests/test_endpoints.py -v
```

Expected: all tests PASS.

- [ ] **Step 9: Run quality checks**

```bash
hk check
```

Fix any issues.

- [ ] **Step 10: Commit**

```bash
git add src/lytter/app.py src/lytter/templates/_recent_plays.html src/lytter/static/styles.css tests/test_helpers.py tests/test_endpoints.py
git commit -m "feat: add _relative_time helper and /html/recent-plays endpoint"
```

---

## Task 4: Extend `/charts/listening-timeline` with `range=all`

**Files:**

- Modify: `src/lytter/app.py` (around line 1250)
- Modify: `tests/test_endpoints.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_endpoints.py`:

```python
def test_timeline_default_returns_json(client):
    response = client.get("/charts/listening-timeline")
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert "layout" in data


def test_timeline_range_all_returns_json(client):
    response = client.get("/charts/listening-timeline?range=all")
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert "layout" in data
```

- [ ] **Step 2: Run tests to confirm default passes, range=all fails**

```bash
uv run pytest tests/test_endpoints.py::test_timeline_default_returns_json tests/test_endpoints.py::test_timeline_range_all_returns_json -v
```

Expected: default PASS (endpoint already exists), `range=all` PASS (ignored param —
FastAPI ignores unknown query params, so this actually passes already). If both pass,
move to step 3.

- [ ] **Step 3: Add `range` param to `listening_timeline`**

Replace the `listening_timeline` function signature and SQL at `app.py:1250`:

```python
@app.get("/charts/listening-timeline")
async def listening_timeline(range: str = Query("year", pattern="^(year|all)$")):
    """Generate listening timeline chart.

    Parameters
    ----------
    range : str
        "year" (default) for past 365 days, "all" for full history.
    """
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()

        if range == "all":
            cursor.execute("""
                SELECT DATE(timestamp, 'unixepoch') as date, COUNT(*) as plays
                FROM musiclibrary
                GROUP BY date
                ORDER BY date ASC
            """)
        else:
            cursor.execute("""
                SELECT DATE(timestamp, 'unixepoch') as date, COUNT(*) as plays
                FROM musiclibrary
                WHERE timestamp >= strftime('%s', 'now', '-365 days')
                GROUP BY date
                ORDER BY date ASC
            """)
        result = cursor.fetchall()
```

Leave everything below (the pandas/plotly part) unchanged.

Note: `range` is a Python builtin — this shadows it locally. Rename the parameter to
`time_range` to avoid shadowing:

```python
async def listening_timeline(time_range: str = Query("year", alias="range", pattern="^(year|all)$")):
```

And replace `if range == "all":` with `if time_range == "all":` in the SQL branch.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_endpoints.py -v
```

Expected: all 4 endpoint tests PASS.

- [ ] **Step 5: Run quality checks**

```bash
hk check
```

- [ ] **Step 6: Commit**

```bash
git add src/lytter/app.py tests/test_endpoints.py
git commit -m "feat: add range=all support to listening-timeline endpoint"
```

---

## Task 5: Update `alltime.html` — add stat cards, timeline, streaks

**Files:**

- Modify: `src/lytter/templates/alltime.html`
- Modify: `src/lytter/app.py` (the `alltime()` route — find with grep for `/all-time`)

- [ ] **Step 1: Locate the `alltime()` route**

```bash
grep -n "all-time\|alltime" src/lytter/app.py | grep "^app\|async def\|@app"
```

Find the route handler and note the line number.

- [ ] **Step 2: Add `_get_dashboard_stats` call to `alltime()`**

In the `alltime()` route handler, add a stats query inside a new
`with sqlite3.connect(DB_NAME) as conn:` block (or add to an existing one if the route
already queries the DB):

```python
@app.get("/all-time", response_class=HTMLResponse)
async def alltime(request: Request):
    """Display all-time charts page."""
    with sqlite3.connect(DB_NAME) as conn:
        stats = _get_dashboard_stats(conn)
    return templates.TemplateResponse(request, "alltime.html", {**stats})
```

If the route already has a body, merge the stats dict into the existing template
context.

- [ ] **Step 3: Add stat cards + timeline + streaks to `alltime.html`**

Replace the content of `src/lytter/templates/alltime.html` with:

```html
{% extends "base.html" %} {% from 'macros.html' import stat_card, loading_spinner %} {%
block title %}All-Time Charts - Last.fm Stats{% endblock %} {% block content %}
<div class="row mb-4">
  <div class="col-12">
    <h1 class="mb-1">All-Time Charts</h1>
    <p class="text-muted mb-3">Top 50 by full listening history</p>
  </div>
</div>

<div class="row mb-4">
  <div class="col">{{ stat_card("Total Scrobbles", total_scrobbles) }}</div>
  <div class="col">{{ stat_card("Unique Artists", unique_artists) }}</div>
  <div class="col">{{ stat_card("Unique Tracks", unique_tracks) }}</div>
  <div class="col">{{ stat_card("Unique Albums", unique_albums) }}</div>
  <div class="col">
    {% if total_listening_time %} {{ stat_card("Listening Time", total_listening_time)
    }} {% if listening_time_known_tracks < listening_time_total_tracks %}
    <small class="text-muted d-block text-center mt-1"
      >{{ listening_time_known_tracks }}/{{ listening_time_total_tracks }} tracks</small
    >
    {% endif %} {% else %} {{ stat_card('Listening Time', '—') }} {% endif %}
  </div>
  <div class="col">{{ stat_card("Current Streak", current_streak ~ " days") }}</div>
  <div class="col">{{ stat_card("Longest Streak", longest_streak ~ " days") }}</div>
</div>

<div class="row mb-4">
  <div class="col-12">
    <div class="card">
      <div class="card-body">
        <h5 class="card-title">Listening Timeline</h5>
        <div id="timeline-chart" style="height: 550px;">
          <div class="d-flex justify-content-center align-items-center h-100">
            <p class="text-muted">Loading chart...</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<div class="row mb-4">
  <div class="col-12">
    <div class="card">
      <div class="card-body">
        <h5 class="card-title">Listening Streaks</h5>
        <div hx-get="/html/streak-history" hx-trigger="load">
          {{ loading_spinner("Loading...") }}
        </div>
      </div>
    </div>
  </div>
</div>

<div class="row mb-4">
  <div class="col-12">
    <ul class="nav nav-tabs" id="item-type-tabs" role="tablist">
      <li class="nav-item" role="presentation">
        <button
          class="nav-link active"
          id="tab-artists"
          data-item-type="artists"
          type="button"
          role="tab"
        >
          Artists
        </button>
      </li>
      <li class="nav-item" role="presentation">
        <button
          class="nav-link"
          id="tab-albums"
          data-item-type="albums"
          type="button"
          role="tab"
        >
          Albums
        </button>
      </li>
      <li class="nav-item" role="presentation">
        <button
          class="nav-link"
          id="tab-songs"
          data-item-type="songs"
          type="button"
          role="tab"
        >
          Songs
        </button>
      </li>
    </ul>
  </div>
</div>

<div class="row mb-4">
  <div class="col-12">
    <div class="card">
      <div class="card-body">
        <div
          class="d-flex align-items-center justify-content-between mb-2 flex-wrap gap-2"
        >
          <div>
            <h5 class="card-title mb-0">Accumulated Listen Count</h5>
            <p class="text-muted small mb-0">
              Cumulative plays — top 10 visible, toggle others in legend
            </p>
          </div>
          <div class="d-flex gap-2">
            <div class="btn-group btn-group-sm" role="group" aria-label="Y-axis scale">
              <button
                type="button"
                class="btn btn-outline-secondary active"
                id="scale-linear"
              >
                Linear
              </button>
              <button type="button" class="btn btn-outline-secondary" id="scale-log">
                Log
              </button>
            </div>
            <div class="btn-group btn-group-sm" role="group" aria-label="Time mode">
              <button
                type="button"
                class="btn btn-outline-secondary active"
                id="time-historical"
              >
                Historical
              </button>
              <button type="button" class="btn btn-outline-secondary" id="time-aligned">
                Aligned
              </button>
            </div>
          </div>
        </div>
        <div id="accumulated-chart" style="height: 500px;"></div>
      </div>
    </div>
  </div>
</div>

<div class="row">
  <div class="col-12">
    <div class="card">
      <div class="card-body">
        <div
          class="d-flex align-items-center justify-content-between mb-2 flex-wrap gap-2"
        >
          <div>
            <h5 class="card-title mb-0">Time Spent</h5>
            <p class="text-muted small mb-0">
              Total listening time (tracks with known duration)
            </p>
          </div>
          <div class="btn-group btn-group-sm" role="group" aria-label="X-axis scale">
            <button
              type="button"
              class="btn btn-outline-secondary active"
              id="ts-scale-linear"
            >
              Linear
            </button>
            <button type="button" class="btn btn-outline-secondary" id="ts-scale-log">
              Log
            </button>
          </div>
        </div>
        <div id="time-spent-chart"></div>
      </div>
    </div>
  </div>
</div>
{% endblock %} {% block scripts %}
<script>
  // Timeline chart (all-time)
  if (typeof Plotly !== "undefined") {
    fetch("/charts/listening-timeline?range=all")
      .then((response) => response.json())
      .then((data) => {
        Plotly.newPlot("timeline-chart", data.data, data.layout, { responsive: true });
      })
      .catch(() => {
        document.getElementById("timeline-chart").innerHTML =
          '<p class="text-muted">Error loading chart</p>';
      });
  } else {
    document.getElementById("timeline-chart").innerHTML =
      '<p class="text-muted">Plotly.js failed to load</p>';
  }

  // Accumulated + time-spent charts (unchanged from before)
  (function () {
    const SPINNER =
      '<div class="d-flex justify-content-center align-items-center" style="height:200px"><p class="text-muted">Loading...</p></div>';
    let currentType = "artists";
    let alignMode = false;
    let accumLogScale = false;
    let tsLogScale = false;
    const accumCache = {};
    const timeCache = {};
    const config = { responsive: true };

    function setLoading(id) {
      const el = document.getElementById(id);
      if (el._plotly) {
        Plotly.purge(el);
        el._plotly = false;
      }
      el.innerHTML = SPINNER;
    }

    function fetchAccum(itemType, align) {
      const key = itemType + "_" + align;
      if (accumCache[key]) return Promise.resolve(accumCache[key]);
      return fetch(
        "/charts/accumulated-listens?item_type=" +
          itemType +
          "&limit=50&align=" +
          align,
      )
        .then((r) => r.json())
        .then((data) => {
          accumCache[key] = data;
          return data;
        });
    }

    function fetchTimeSpent(itemType) {
      if (timeCache[itemType]) return Promise.resolve(timeCache[itemType]);
      return fetch("/charts/time-spent?item_type=" + itemType + "&limit=50")
        .then((r) => r.json())
        .then((data) => {
          timeCache[itemType] = data;
          return data;
        });
    }

    function attachAccumHover(chartId) {
      const el = document.getElementById(chartId);
      const n = el.data.length;
      const colors = el._fullData.map((t) => t.line.color);

      function highlight(hoveredIndex) {
        const update = { "line.width": [], opacity: [], "line.color": [] };
        for (let i = 0; i < n; i++) {
          update["line.width"].push(i === hoveredIndex ? 5 : 1);
          update.opacity.push(i === hoveredIndex ? 1 : 0.15);
          update["line.color"].push(colors[i]);
        }
        Plotly.restyle(chartId, update);
      }

      function resetAll() {
        Plotly.restyle(chartId, {
          "line.width": Array(n).fill(2),
          opacity: Array(n).fill(1),
          "line.color": colors,
        });
      }

      el.on("plotly_hover", (evt) => highlight(evt.points[0].curveNumber));
      el.on("plotly_unhover", resetAll);

      setTimeout(() => {
        el.querySelectorAll(".legend .traces .legendtoggle").forEach((item, i) => {
          item.addEventListener("mouseenter", () => highlight(i));
          item.addEventListener("mouseleave", resetAll);
        });
      }, 100);
    }

    function renderAccum(data) {
      const d = JSON.parse(JSON.stringify(data));
      d.layout.yaxis = Object.assign({}, d.layout.yaxis, {
        type: accumLogScale ? "log" : "linear",
      });
      const el = document.getElementById("accumulated-chart");
      el.innerHTML = "";
      Plotly.newPlot("accumulated-chart", d.data, d.layout, config);
      el._plotly = true;
      attachAccumHover("accumulated-chart");
    }

    function renderTimeSpent(data) {
      const d = JSON.parse(JSON.stringify(data));
      d.layout.xaxis = Object.assign({}, d.layout.xaxis, {
        type: tsLogScale ? "log" : "linear",
      });
      const el = document.getElementById("time-spent-chart");
      el.innerHTML = "";
      Plotly.newPlot("time-spent-chart", d.data, d.layout, config);
      el._plotly = true;
    }

    function loadAccum(itemType, align) {
      setLoading("accumulated-chart");
      fetchAccum(itemType, align)
        .then(renderAccum)
        .catch(() => {
          document.getElementById("accumulated-chart").innerHTML =
            '<p class="text-muted p-3">Error loading chart</p>';
        });
    }

    function loadTimeSpent(itemType) {
      setLoading("time-spent-chart");
      fetchTimeSpent(itemType)
        .then(renderTimeSpent)
        .catch(() => {
          document.getElementById("time-spent-chart").innerHTML =
            '<p class="text-muted p-3">Error loading chart</p>';
        });
    }

    function loadAll(itemType) {
      loadAccum(itemType, alignMode);
      loadTimeSpent(itemType);
    }

    document.querySelectorAll("#item-type-tabs .nav-link").forEach((btn) => {
      btn.addEventListener("click", () => {
        document
          .querySelectorAll("#item-type-tabs .nav-link")
          .forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        const newType = btn.dataset.itemType;
        if (newType !== currentType) {
          currentType = newType;
          loadAll(newType);
        }
      });
    });

    document.getElementById("scale-linear").addEventListener("click", () => {
      if (accumLogScale) {
        accumLogScale = false;
        document.getElementById("scale-linear").classList.add("active");
        document.getElementById("scale-log").classList.remove("active");
        Plotly.relayout("accumulated-chart", { "yaxis.type": "linear" });
      }
    });
    document.getElementById("scale-log").addEventListener("click", () => {
      if (!accumLogScale) {
        accumLogScale = true;
        document.getElementById("scale-log").classList.add("active");
        document.getElementById("scale-linear").classList.remove("active");
        Plotly.relayout("accumulated-chart", { "yaxis.type": "log" });
      }
    });
    document.getElementById("time-historical").addEventListener("click", () => {
      if (alignMode) {
        alignMode = false;
        document.getElementById("time-historical").classList.add("active");
        document.getElementById("time-aligned").classList.remove("active");
        loadAccum(currentType, false);
      }
    });
    document.getElementById("time-aligned").addEventListener("click", () => {
      if (!alignMode) {
        alignMode = true;
        document.getElementById("time-aligned").classList.add("active");
        document.getElementById("time-historical").classList.remove("active");
        loadAccum(currentType, true);
      }
    });
    document.getElementById("ts-scale-linear").addEventListener("click", () => {
      if (tsLogScale) {
        tsLogScale = false;
        document.getElementById("ts-scale-linear").classList.add("active");
        document.getElementById("ts-scale-log").classList.remove("active");
        Plotly.relayout("time-spent-chart", { "xaxis.type": "linear" });
      }
    });
    document.getElementById("ts-scale-log").addEventListener("click", () => {
      if (!tsLogScale) {
        tsLogScale = true;
        document.getElementById("ts-scale-log").classList.add("active");
        document.getElementById("ts-scale-linear").classList.remove("active");
        Plotly.relayout("time-spent-chart", { "xaxis.type": "log" });
      }
    });

    loadAll("artists");
  })();
</script>
{% endblock %}
```

- [ ] **Step 4: Run quality checks**

```bash
hk check
```

- [ ] **Step 5: Commit**

```bash
git add src/lytter/templates/alltime.html src/lytter/app.py
git commit -m "feat: add stat cards, timeline, and streaks to all-time page"
```

---

## Task 6: Update `index.html` — strip old content, add Recent Plays

**Files:**

- Modify: `src/lytter/templates/index.html`

- [ ] **Step 1: Replace `index.html`**

Replace the entire content of `src/lytter/templates/index.html` with:

```html
{% extends "base.html" %} {% from 'macros.html' import loading_spinner %} {% block title
%}Recent - Last.fm Stats{% endblock %} {% block content %}
<div class="row">
  <div class="col-12">
    <h1 class="mb-4">Recently</h1>
  </div>
</div>

{% if current_track %}
<div class="row mb-4">
  <div class="col-12">
    <div class="card">
      <div class="card-body">
        <h5 class="card-title">🎧 Currently Playing</h5>
        <h6 class="card-subtitle mb-2 text-muted">{{ current_track.artist }}</h6>
        <p class="card-text">
          <strong>{{ current_track.title }}</strong>
          <br />
          <small>from {{ current_track.album }}</small>
        </p>
        <a
          href="/artist/{{ current_track.artist|urlencode }}"
          class="btn btn-primary btn-sm"
          >Artist</a
        >
        <a
          href="/album/{{ current_track.artist|urlencode }}/{{ current_track.album|urlencode }}"
          class="btn btn-primary btn-sm ms-2"
          >Album</a
        >
        <a
          href="/song/{{ current_track.artist|urlencode }}/{{ current_track.title|urlencode }}"
          class="btn btn-primary btn-sm ms-2"
          >Song</a
        >
      </div>
    </div>
  </div>
</div>
{% endif %}

<div class="row mb-4">
  <div class="col-lg-6 mb-4">
    <div class="card h-100">
      <div class="card-body">
        <h5 class="card-title">Recent Plays</h5>
        <div hx-get="/html/recent-plays" hx-trigger="load">
          {{ loading_spinner("Loading...") }}
        </div>
      </div>
    </div>
  </div>
  <div class="col-lg-6 mb-4">
    <div class="card h-100">
      <div class="card-body">
        <h5 class="card-title">Activity Calendar</h5>
        <div hx-get="/html/calendar-heatmap" hx-trigger="load">
          {{ loading_spinner("Loading calendar...") }}
        </div>
      </div>
    </div>
  </div>
</div>

<div class="row">
  <div class="col-lg-6 mb-4">
    <div class="card">
      <div class="card-body">
        <h5 class="card-title">On This Day</h5>
        <div hx-get="/html/on-this-day" hx-trigger="load">
          {{ loading_spinner("Loading...") }}
        </div>
      </div>
    </div>
  </div>
  <div class="col-lg-6 mb-4">
    <div class="card">
      <div class="card-body">
        <h5 class="card-title">Recent Favorites</h5>
        <div hx-get="/html/recent-favorites" hx-trigger="load">
          {{ loading_spinner("Loading favorites...") }}
        </div>
      </div>
    </div>
  </div>
</div>
{% endblock %}
```

Note: the `index()` route no longer needs to pass stat variables — it only passes
`current_track`. Verify the route after Task 2 already does this
(`{**stats, "current_track": current_track}`). Since `index.html` no longer uses the
stat variables, having them in context is harmless, but you may clean up `index()` to
skip the `_get_dashboard_stats(conn)` call:

```python
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Display main dashboard page."""
    current_track = None
    try:
        user = network.get_user(USER_NAME)
        now_playing = user.get_now_playing()
        if now_playing:
            current_track = {
                "artist": str(now_playing.artist),
                "title": str(now_playing.title),
                "album": str(now_playing.get_album()) if now_playing.get_album() else "Unknown",
            }
    except Exception:
        pass
    return templates.TemplateResponse(request, "index.html", {"current_track": current_track})
```

- [ ] **Step 2: Run quality checks**

```bash
hk check
```

- [ ] **Step 3: Commit**

```bash
git add src/lytter/templates/index.html src/lytter/app.py
git commit -m "feat: redesign front page as recency-focused view"
```

---

## Task 7: Responsive navbar in `base.html`

**Files:**

- Modify: `src/lytter/templates/base.html`

- [ ] **Step 1: Replace the navbar section**

In `base.html`, replace the `<nav>` block (lines 19–45) with:

```html
<nav class="navbar navbar-expand-lg navbar-dark">
  <div class="container">
    <a class="navbar-brand" href="/">🎵 Last.fm Stats</a>
    <button
      class="navbar-toggler"
      type="button"
      data-bs-toggle="collapse"
      data-bs-target="#main-nav"
      aria-controls="main-nav"
      aria-expanded="false"
      aria-label="Toggle navigation"
    >
      <span class="navbar-toggler-icon"></span>
    </button>
    <div class="collapse navbar-collapse" id="main-nav">
      <div class="navbar-nav me-auto">
        <a class="nav-link" href="/all-time">All Time</a>
        <a class="nav-link" href="/yearly">Yearly Stats</a>
        <a class="nav-link" href="/duration-stats">Duration Stats</a>
        <a class="nav-link" href="/genre-stats">Genre Stats</a>
        <a class="nav-link" href="/discovery">Discovery</a>
        <a class="nav-link" href="/artist-stats">Artist Stats</a>
        <a class="nav-link" href="/compare">Compare</a>
      </div>
      <div class="navbar-nav">
        <div class="position-relative" style="width: 300px;">
          <input
            type="search"
            id="artist-search"
            class="form-control"
            placeholder="Search artists, albums, songs..."
            autocomplete="off"
          />
          <div
            id="search-results"
            class="position-absolute w-100 mt-1"
            style="z-index: 1050;
                          display: none;
                          max-height: 400px;
                          overflow-y: auto"
          ></div>
        </div>
      </div>
    </div>
  </div>
</nav>
```

Key changes:

- Added `navbar-toggler` button (hamburger) — Bootstrap JS handles collapse
  automatically via `data-bs-toggle="collapse"`
- Wrapped nav links in `collapse navbar-collapse` div with `id="main-nav"`
- Changed `<div class="navbar-nav">` to `<div class="navbar-nav me-auto">` so links push
  search to the right on desktop
- Moved search bar inside the collapsible section so it's accessible on mobile

- [ ] **Step 2: Run quality checks**

```bash
hk check
```

- [ ] **Step 3: Commit**

```bash
git add src/lytter/templates/base.html
git commit -m "feat: add responsive hamburger nav for mobile"
```

---

## Self-Review Checklist

**Spec coverage:**

- [x] Move stat cards to all-time — Task 5 adds them to `alltime.html`, Task 6 strips
      from `index.html`
- [x] Front page: Currently Playing, Activity Calendar, On This Day, Recent Favorites —
      Task 6
- [x] New Recent Plays card — Tasks 3 + 6
- [x] CSS fade on recent plays — Task 3 (`recent-plays-fade` gradient)
- [x] Track + artist links + relative time — Task 3 (`_recent_plays.html`)
- [x] Listening timeline moved + expanded to all-time — Tasks 4 + 5
- [x] Listening streaks moved — Task 5
- [x] `_get_dashboard_stats` shared helper — Task 2
- [x] Responsive navbar — Task 7

**No gaps found.**
