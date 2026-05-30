# Name Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or superpowers:executing-plans
> to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `artist_key`, `album_key`, `track_key` columns to `musiclibrary` so that
capitalization/unicode/feat. variants of the same name are grouped together in all
queries, while raw display names are preserved.

**Architecture:** A single `normalize_name(s, field)` function produces deterministic
keys. Keys are stored alongside raw strings in the DB, computed on insert and backfilled
on startup. All GROUP BY queries switch to key columns; display names are picked as the
most-frequent raw variant per key group via correlated subquery.

**Tech Stack:** Python 3, SQLite, pytest, `unicodedata`, `re` (already in use)

---

## File map

| File                             | Change                                                                                                        |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `src/lytter/app.py`              | Add `normalize_name()`, update `init_db()`, add `backfill_keys()`, update INSERT, update all GROUP BY queries |
| `src/lytter/gap_checker.py`      | Update INSERT to compute and store keys                                                                       |
| `src/lytter/meta_updater.py`     | Update `_get_artists()` GROUP BY queries                                                                      |
| `src/lytter/duration_updater.py` | Update `_get_tracks()` GROUP BY queries                                                                       |
| `src/lytter/db_status.py`        | Update COUNT(DISTINCT) to use key columns                                                                     |
| `tests/conftest.py`              | Add key columns to test schema and fixture rows                                                               |
| `tests/test_normalize.py`        | New — unit tests for `normalize_name()`                                                                       |

---

## Task 1: `normalize_name()` function

**Files:**

- Create: `tests/test_normalize.py`
- Modify: `src/lytter/app.py` (after `normalize_text`, around line 126)

- [ ] **Step 1: Write failing tests**

Create `tests/test_normalize.py`:

```python
"""Unit tests for normalize_name()."""

import pytest

from lytter.app import normalize_name


@pytest.mark.parametrize("raw,expected", [
    # Case
    ("Angine de Poitrine", "angine de poitrine"),
    ("RADIOHEAD", "radiohead"),
    # Whitespace
    ("  Sigur  Rós  ", "sigur ros"),
    # Diacritics
    ("Sigur Rós", "sigur ros"),
    ("Björk", "bjork"),
    ("café tacvba", "cafe tacvba"),
    # Ampersand
    ("Simon & Garfunkel", "simon and garfunkel"),
    ("Simon&Garfunkel", "simon&garfunkel"),  # no spaces = not matched
    # Unicode NFC/NFD round-trip
    ("é", "e"),  # e + combining acute = é, then stripped
])
def test_normalize_artist(raw, expected):
    assert normalize_name(raw, "artist") == expected


@pytest.mark.parametrize("raw,expected", [
    # feat. variants normalized only for track field
    ("Song (feat. Other Artist)", "song feat. other artist"),
    ("Song (Feat. Other Artist)", "song feat. other artist"),
    ("Song [feat. Other]", "song feat. other"),
    ("Song ft. Other", "song feat. other"),
    ("Song featuring Other", "song feat. other"),
    # artist field: feat. NOT normalized
])
def test_normalize_track_feat(raw, expected):
    assert normalize_name(raw, "track") == expected


def test_normalize_artist_feat_unchanged():
    """feat. variants are NOT collapsed for artist field."""
    assert normalize_name("Artist feat. Other", "artist") == "artist feat. other"
    # Only lowercased and stripped, not restructured


def test_normalize_empty():
    assert normalize_name("", "artist") == ""
    assert normalize_name("", "track") == ""


def test_normalize_album():
    assert normalize_name("OK Computer", "album") == "ok computer"
    assert normalize_name("Ágætis byrjun", "album") == "agaetis byrjun"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_normalize.py -v
```

Expected: `ImportError: cannot import name 'normalize_name' from 'lytter.app'`

- [ ] **Step 3: Implement `normalize_name()` in `app.py`**

Add after the `normalize_text` function (around line 126), before `init_db`:

```python
_FEAT_PAREN_RE = re.compile(
    r"[\(\[]\s*(?:feat\.?|ft\.?|featuring)\s+([^\)\]]+)[\)\]]",
    re.IGNORECASE,
)
_FEAT_BARE_RE = re.compile(r"\b(?:ft\.?|featuring)\b", re.IGNORECASE)


def normalize_name(s: str, field: str = "artist") -> str:
    """Produce a normalized grouping key for an artist, album, or track name.

    Parameters
    ----------
    s : str
        Raw name string.
    field : str
        One of "artist", "album", "track". Track gets feat. normalization.

    Returns
    -------
    str
        Lowercase, diacritic-free, whitespace-collapsed key.
    """
    if not s:
        return ""
    # 1. NFC unicode normalization
    s = unicodedata.normalize("NFC", s)
    # 2. Whitespace
    s = " ".join(s.split())
    # 3. Lowercase
    s = s.lower()
    # 4. Strip diacritics
    nfd = unicodedata.normalize("NFD", s)
    s = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    # 5. Feat. normalization — track only
    if field == "track":
        s = _FEAT_PAREN_RE.sub(r"feat. \1", s)
        s = _FEAT_BARE_RE.sub("feat.", s)
        s = " ".join(s.split())  # re-collapse after substitution
    # 6. Ampersand (with surrounding spaces only)
    s = s.replace(" & ", " and ")
    return s
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_normalize.py -v
```

Expected: all green.

- [ ] **Step 5: Run full check**

```bash
hk check
```

Fix any lint issues before committing.

- [ ] **Step 6: Commit**

```bash
git add src/lytter/app.py tests/test_normalize.py
git commit -m "feat: add normalize_name() for artist/album/track key generation"
```

---

## Task 2: Schema migration and backfill

**Files:**

- Modify: `src/lytter/app.py` (`init_db`, new `backfill_keys`)
- Modify: `tests/conftest.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_helpers.py` (after existing tests):

```python
def test_backfill_keys_populates_columns(tmp_path, monkeypatch):
    """backfill_keys() computes correct keys for existing rows."""
    import sqlite3
    import lytter.app as app_module
    from lytter.app import backfill_keys, normalize_name

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
    """init_db() adds key columns to existing DB without dropping data."""
    import sqlite3
    import lytter.app as app_module
    from lytter.app import init_db

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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_helpers.py::test_backfill_keys_populates_columns tests/test_helpers.py::test_init_db_adds_key_columns -v
```

Expected: `ImportError: cannot import name 'backfill_keys'`

- [ ] **Step 3: Implement schema migration in `init_db()` and add `backfill_keys()`**

In `app.py`, replace the `init_db` function body — add column migration after the
existing `CREATE TABLE IF NOT EXISTS musiclibrary` block, and call `backfill_keys` at
the end:

```python
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
                timestamp INTEGER UNIQUE NOT NULL,
                artist_key TEXT,
                album_key TEXT,
                track_key TEXT
            )
        """)
        # Migrate existing DBs that predate key columns
        cursor.execute("PRAGMA table_info(musiclibrary)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        for col in ("artist_key", "album_key", "track_key"):
            if col not in existing_cols:
                cursor.execute(f"ALTER TABLE musiclibrary ADD COLUMN {col} TEXT")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_artist_key
            ON musiclibrary(artist_key)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_artist_album_key
            ON musiclibrary(artist_key, album_key)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_artist_track_key
            ON musiclibrary(artist_key, track_key)
        """)
        # … rest of CREATE TABLE statements unchanged (track_durations, lyrics, etc.) …
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
        backfill_keys(conn)
```

Add `backfill_keys` just before `init_db`:

```python
def backfill_keys(conn: sqlite3.Connection) -> None:
    """Populate artist_key/album_key/track_key for rows where they are NULL."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, artist, album, track FROM musiclibrary WHERE artist_key IS NULL"
    )
    rows = cursor.fetchall()
    for row_id, artist, album, track in rows:
        cursor.execute(
            "UPDATE musiclibrary SET artist_key=?, album_key=?, track_key=? WHERE id=?",
            (
                normalize_name(artist, "artist"),
                normalize_name(album or "", "album"),
                normalize_name(track, "track"),
                row_id,
            ),
        )
    conn.commit()
```

- [ ] **Step 4: Update `tests/conftest.py` to include key columns**

Replace the `test_db` fixture:

```python
"""Pytest configuration and shared fixtures for lytter tests."""

import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

import lytter.app as app_module
from lytter.app import app, normalize_name


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
                timestamp INTEGER UNIQUE NOT NULL,
                artist_key TEXT,
                album_key TEXT,
                track_key TEXT
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
        raw_rows = [
            ("Radiohead", None, "OK Computer", None, "Paranoid Android", None, now - 120),
            ("Radiohead", None, "OK Computer", None, "Karma Police", None, now - 480),
            ("K.Flay", None, "Every Where Is Some Where", None, "Blood in the Cut", None, now - 720),
        ]
        rows = [
            r + (
                normalize_name(r[0], "artist"),
                normalize_name(r[2] or "", "album"),
                normalize_name(r[4], "track"),
            )
            for r in raw_rows
        ]
        conn.executemany(
            "INSERT INTO musiclibrary "
            "(artist, artist_mbid, album, album_mbid, track, track_mbid, timestamp, artist_key, album_key, track_key) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
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
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_helpers.py -v
```

Expected: all green (including new backfill tests).

- [ ] **Step 6: Run full check**

```bash
hk check
```

- [ ] **Step 7: Commit**

```bash
git add src/lytter/app.py tests/conftest.py tests/test_helpers.py
git commit -m "feat: add key columns to musiclibrary schema with backfill on startup"
```

---

## Task 3: Update INSERT paths

**Files:**

- Modify: `src/lytter/app.py` (line ~914)
- Modify: `src/lytter/gap_checker.py` (line ~149)

- [ ] **Step 1: Write failing test**

Add to `tests/test_helpers.py`:

```python
def test_insert_computes_keys(tmp_path, monkeypatch):
    """Rows inserted via the app INSERT path have key columns populated."""
    import sqlite3
    import lytter.app as app_module
    from lytter.app import normalize_name

    db = tmp_path / "ins.db"
    monkeypatch.setattr(app_module, "DB_NAME", db)
    app_module.init_db()

    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO musiclibrary
               (artist, artist_mbid, album, album_mbid, track, track_mbid, timestamp,
                artist_key, album_key, track_key)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                "Angine de Poitrine", "", "Un Album", "", "Une Chanson", "", 12345,
                normalize_name("Angine de Poitrine", "artist"),
                normalize_name("Un Album", "album"),
                normalize_name("Une Chanson", "track"),
            ),
        )
        row = conn.execute(
            "SELECT artist_key, album_key, track_key FROM musiclibrary WHERE timestamp=12345"
        ).fetchone()

    assert row[0] == "angine de poitrine"
    assert row[1] == "un album"
    assert row[2] == "une chanson"
```

(This test verifies the column contract; the next steps wire the real INSERT.)

- [ ] **Step 2: Run test to verify it passes as-is**

```bash
uv run pytest tests/test_helpers.py::test_insert_computes_keys -v
```

Expected: PASS (the test inserts directly with computed keys — we're confirming the
schema accepts the values before wiring the application code).

- [ ] **Step 3: Update INSERT in `app.py`**

Find the INSERT block around line 914 and add key computation:

```python
# Insert new scrobble
try:
    artist_raw = scrobble["artist"]["#text"]
    album_raw = scrobble["album"]["#text"]
    track_raw = scrobble["name"]
    cursor.execute(
        """
        INSERT INTO musiclibrary
        (artist, artist_mbid, album, album_mbid, track, track_mbid, timestamp,
         artist_key, album_key, track_key)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            artist_raw,
            scrobble["artist"]["mbid"],
            album_raw,
            scrobble["album"]["mbid"],
            track_raw,
            scrobble["mbid"],
            scrobble_timestamp,
            normalize_name(artist_raw, "artist"),
            normalize_name(album_raw, "album"),
            normalize_name(track_raw, "track"),
        ),
    )
    conn.commit()
    new_scrobbles_count += 1
    page_new_count += 1
except sqlite3.Error as e:
    print(f"\nDatabase error: {e}")
    conn.rollback()
```

- [ ] **Step 4: Update INSERT in `gap_checker.py`**

Find the INSERT block around line 149 and update similarly:

```python
if not dry_run:
    try:
        cursor.execute(
            """
            INSERT INTO musiclibrary
            (artist, artist_mbid, album, album_mbid, track, track_mbid, timestamp,
             artist_key, album_key, track_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                scrobble["artist"],
                scrobble["artist_mbid"],
                scrobble["album"],
                scrobble["album_mbid"],
                scrobble["track"],
                scrobble["track_mbid"],
                scrobble["timestamp"],
                normalize_name(scrobble["artist"], "artist"),
                normalize_name(scrobble["album"] or "", "album"),
                normalize_name(scrobble["track"], "track"),
            ),
        )
        conn.commit()
        added_count += 1
    except sqlite3.IntegrityError:
        pass
```

Add the import at the top of `gap_checker.py`:

```python
from lytter.app import DB_NAME, MINIMUM_VALID_TIMESTAMP, normalize_name
```

(Check what is already imported from `lytter.app` and add `normalize_name` to the
existing import.)

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest -v
```

Expected: all green.

- [ ] **Step 6: Run full check**

```bash
hk check
```

- [ ] **Step 7: Commit**

```bash
git add src/lytter/app.py src/lytter/gap_checker.py tests/test_helpers.py
git commit -m "feat: compute and store key columns on scrobble insert"
```

---

## Task 4: Update COUNT(DISTINCT) queries

**Files:**

- Modify: `src/lytter/app.py` (lines 620, 622, 624–626)
- Modify: `src/lytter/db_status.py` (line 32)

- [ ] **Step 1: Write failing test**

Add to `tests/test_helpers.py`:

```python
def test_dashboard_stats_deduplicates_by_key(tmp_path, monkeypatch):
    """unique_artists counts key groups, not raw strings."""
    import sqlite3
    import lytter.app as app_module
    from lytter.app import normalize_name

    db = tmp_path / "dedup.db"
    monkeypatch.setattr(app_module, "DB_NAME", db)
    app_module.init_db()

    with sqlite3.connect(db) as conn:
        rows = [
            ("Angine de Poitrine", None, "Album", None, "Track", None, 1000,
             normalize_name("Angine de Poitrine", "artist"),
             normalize_name("Album", "album"),
             normalize_name("Track", "track")),
            ("Angine de poitrine", None, "Album", None, "Track", None, 2000,
             normalize_name("Angine de poitrine", "artist"),
             normalize_name("Album", "album"),
             normalize_name("Track", "track")),
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_helpers.py::test_dashboard_stats_deduplicates_by_key -v
```

Expected: FAIL — `assert 2 == 1` (currently counts raw strings).

- [ ] **Step 3: Update COUNT(DISTINCT) in `app.py` `_get_dashboard_stats`**

Find lines 620–627 and replace:

```python
cursor.execute("SELECT COUNT(DISTINCT artist_key) FROM musiclibrary")
unique_artists = cursor.fetchone()[0]
cursor.execute("SELECT COUNT(DISTINCT track_key) FROM musiclibrary")
unique_tracks = cursor.fetchone()[0]
cursor.execute(
    "SELECT COUNT(DISTINCT album_key) FROM musiclibrary WHERE album_key != ''"
)
unique_albums = cursor.fetchone()[0]
```

- [ ] **Step 4: Update COUNT(DISTINCT) in `db_status.py`**

Find line 32 and replace:

```python
cursor.execute("SELECT COUNT(DISTINCT artist_key) FROM musiclibrary")
unique_artists = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(DISTINCT track_key) FROM musiclibrary")
unique_tracks = cursor.fetchone()[0]
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_helpers.py -v
```

Expected: all green.

- [ ] **Step 6: Run full check**

```bash
hk check
```

- [ ] **Step 7: Commit**

```bash
git add src/lytter/app.py src/lytter/db_status.py tests/test_helpers.py
git commit -m "feat: use key columns for COUNT(DISTINCT) unique stats"
```

---

## Task 5: Update top-N display queries

**Files:**

- Modify: `src/lytter/app.py` (lines 1225, 1239, 1256, 1273)

- [ ] **Step 1: Write failing test**

Add to `tests/test_endpoints.py` (or after existing endpoint tests):

```python
def test_top_artists_deduplicates(client, test_db):
    """Top artists endpoint merges capitalization variants."""
    import sqlite3
    import lytter.app as app_module
    from lytter.app import normalize_name

    with sqlite3.connect(test_db) as conn:
        extra = [
            ("Radiohead", None, "Pablo Honey", None, "Creep", None,
             int(__import__("time").time()) - 10,
             normalize_name("Radiohead", "artist"),
             normalize_name("Pablo Honey", "album"),
             normalize_name("Creep", "track")),
            ("radiohead", None, "Pablo Honey", None, "Stop Whispering", None,
             int(__import__("time").time()) - 20,
             normalize_name("radiohead", "artist"),
             normalize_name("Pablo Honey", "album"),
             normalize_name("Stop Whispering", "track")),
        ]
        conn.executemany(
            "INSERT INTO musiclibrary "
            "(artist, artist_mbid, album, album_mbid, track, track_mbid, timestamp, "
            "artist_key, album_key, track_key) VALUES (?,?,?,?,?,?,?,?,?,?)",
            extra,
        )

    response = client.get("/top-artists")
    assert response.status_code == 200
    artists = response.json()["artists"]
    names = [a["artist"] for a in artists]
    # "Radiohead" and "radiohead" must appear as a single entry
    radiohead_entries = [n for n in names if n.lower() == "radiohead"]
    assert len(radiohead_entries) == 1
    # Total plays for that entry = 2 (fixture) + 2 (extra) = 4
    radiohead = next(a for a in artists if a["artist"].lower() == "radiohead")
    assert radiohead["plays"] == 4  # noqa: PLR2004
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_endpoints.py::test_top_artists_deduplicates -v
```

Expected: FAIL — two "Radiohead" entries appear instead of one.

- [ ] **Step 3: Update `top_artists` (JSON, line ~1224)**

Replace the query inside `async def top_artists()`:

```python
cursor.execute("""
    SELECT
        (SELECT m2.artist FROM musiclibrary m2
         WHERE m2.artist_key = m.artist_key
         GROUP BY m2.artist ORDER BY COUNT(*) DESC LIMIT 1) AS artist,
        COUNT(*) AS plays
    FROM musiclibrary m
    GROUP BY m.artist_key
    ORDER BY plays DESC
    LIMIT 50
""")
```

- [ ] **Step 4: Update `top_artists_html` (line ~1238)**

Same query inside `async def top_artists_html()`.

- [ ] **Step 5: Update `top_albums_html` (line ~1255)**

```python
cursor.execute("""
    SELECT
        (SELECT m2.artist FROM musiclibrary m2
         WHERE m2.artist_key = m.artist_key
         GROUP BY m2.artist ORDER BY COUNT(*) DESC LIMIT 1) AS artist,
        (SELECT m2.album FROM musiclibrary m2
         WHERE m2.artist_key = m.artist_key AND m2.album_key = m.album_key
         GROUP BY m2.album ORDER BY COUNT(*) DESC LIMIT 1) AS album,
        COUNT(*) AS plays
    FROM musiclibrary m
    WHERE m.album_key != ''
    GROUP BY m.artist_key, m.album_key
    ORDER BY plays DESC
    LIMIT 50
""")
```

- [ ] **Step 6: Update `top_songs_html` (line ~1271)**

```python
cursor.execute("""
    SELECT
        (SELECT m2.artist FROM musiclibrary m2
         WHERE m2.artist_key = m.artist_key
         GROUP BY m2.artist ORDER BY COUNT(*) DESC LIMIT 1) AS artist,
        (SELECT m2.track FROM musiclibrary m2
         WHERE m2.artist_key = m.artist_key AND m2.track_key = m.track_key
         GROUP BY m2.track ORDER BY COUNT(*) DESC LIMIT 1) AS track,
        COUNT(*) AS plays
    FROM musiclibrary m
    GROUP BY m.artist_key, m.track_key
    ORDER BY plays DESC
    LIMIT 50
""")
```

- [ ] **Step 7: Run tests**

```bash
uv run pytest tests/ -v
```

Expected: all green.

- [ ] **Step 8: Run full check**

```bash
hk check
```

- [ ] **Step 9: Commit**

```bash
git add src/lytter/app.py tests/test_endpoints.py
git commit -m "feat: group top-N queries by key columns to merge capitalization variants"
```

---

## Task 6: Update `_get_dashboard_stats` GROUP BY

**Files:**

- Modify: `src/lytter/app.py` (lines 629–634)

- [ ] **Step 1: Write failing test**

Add to `tests/test_helpers.py`:

```python
def test_dashboard_listening_time_merges_variants(tmp_path, monkeypatch):
    """Listening time sums plays across capitalization variants of the same track."""
    import sqlite3
    import lytter.app as app_module
    from lytter.app import normalize_name

    db = tmp_path / "lt.db"
    monkeypatch.setattr(app_module, "DB_NAME", db)
    app_module.init_db()

    now = int(__import__("time").time())
    with sqlite3.connect(db) as conn:
        rows = [
            ("Radiohead", None, "OK Computer", None, "Paranoid Android", None, now - 100,
             normalize_name("Radiohead", "artist"),
             normalize_name("OK Computer", "album"),
             normalize_name("Paranoid Android", "track")),
            ("radiohead", None, "OK Computer", None, "paranoid android", None, now - 200,
             normalize_name("radiohead", "artist"),
             normalize_name("OK Computer", "album"),
             normalize_name("paranoid android", "track")),
        ]
        conn.executemany(
            "INSERT INTO musiclibrary "
            "(artist, artist_mbid, album, album_mbid, track, track_mbid, timestamp, "
            "artist_key, album_key, track_key) VALUES (?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        conn.execute(
            "INSERT INTO track_durations (artist, track, duration_ms, fetched_at) VALUES (?,?,?,?)",
            ("Radiohead", "Paranoid Android", 383000, now),
        )
        stats = app_module._get_dashboard_stats(conn)

    # 2 plays × 383000ms = 766000ms — but only if variants are merged
    assert stats["listening_time_known_tracks"] == 1  # one unique key group
    assert stats["listening_time_total_tracks"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_helpers.py::test_dashboard_listening_time_merges_variants -v
```

Expected: FAIL — currently reports 2 unique track groups (not 1).

- [ ] **Step 3: Update GROUP BY in `_get_dashboard_stats`**

Replace lines 629–634:

```python
cursor.execute("""
    SELECT COUNT(*) as plays, MAX(td.duration_ms) as duration_ms
    FROM musiclibrary m
    LEFT JOIN track_durations td ON td.artist = m.artist AND td.track = m.track
    GROUP BY m.artist_key, m.track_key
""")
rows = cursor.fetchall()
total_ms = sum(row[0] * row[1] for row in rows if row[1])
known_track_count = sum(1 for row in rows if row[1])
total_track_count = len(rows)
```

Note: index positions changed — `row[0]` is plays, `row[1]` is duration_ms (artist/track
columns dropped since they are not used in the calculation).

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_helpers.py -v
```

Expected: all green.

- [ ] **Step 5: Run full check**

```bash
hk check
```

- [ ] **Step 6: Commit**

```bash
git add src/lytter/app.py tests/test_helpers.py
git commit -m "feat: merge key variants in listening time calculation"
```

---

## Task 7: Update `recent_stats` queries

**Files:**

- Modify: `src/lytter/app.py` (lines 1436–1513)

No new tests needed — the endpoint test suite already covers `/recent-stats`. This task
updates all six GROUP BY queries in `recent_stats()` to use the same key+display-name
pattern.

- [ ] **Step 1: Replace week_artists query (line ~1436)**

```python
cursor.execute("""
    SELECT
        (SELECT m2.artist FROM musiclibrary m2
         WHERE m2.artist_key = m.artist_key
         GROUP BY m2.artist ORDER BY COUNT(*) DESC LIMIT 1) AS artist,
        COUNT(*) AS plays
    FROM musiclibrary m
    WHERE m.timestamp >= strftime('%s', 'now', '-7 days')
    GROUP BY m.artist_key
    ORDER BY plays DESC
    LIMIT 5
""")
```

- [ ] **Step 2: Replace week_albums query (line ~1449)**

```python
cursor.execute("""
    SELECT
        (SELECT m2.artist FROM musiclibrary m2
         WHERE m2.artist_key = m.artist_key
         GROUP BY m2.artist ORDER BY COUNT(*) DESC LIMIT 1) AS artist,
        (SELECT m2.album FROM musiclibrary m2
         WHERE m2.artist_key = m.artist_key AND m2.album_key = m.album_key
         GROUP BY m2.album ORDER BY COUNT(*) DESC LIMIT 1) AS album,
        COUNT(*) AS plays
    FROM musiclibrary m
    WHERE m.timestamp >= strftime('%s', 'now', '-7 days')
        AND m.album_key != ''
    GROUP BY m.artist_key, m.album_key
    ORDER BY plays DESC
    LIMIT 5
""")
```

- [ ] **Step 3: Replace week_songs query (line ~1463)**

```python
cursor.execute("""
    SELECT
        (SELECT m2.artist FROM musiclibrary m2
         WHERE m2.artist_key = m.artist_key
         GROUP BY m2.artist ORDER BY COUNT(*) DESC LIMIT 1) AS artist,
        (SELECT m2.track FROM musiclibrary m2
         WHERE m2.artist_key = m.artist_key AND m2.track_key = m.track_key
         GROUP BY m2.track ORDER BY COUNT(*) DESC LIMIT 1) AS track,
        COUNT(*) AS plays
    FROM musiclibrary m
    WHERE m.timestamp >= strftime('%s', 'now', '-7 days')
    GROUP BY m.artist_key, m.track_key
    ORDER BY plays DESC
    LIMIT 5
""")
```

- [ ] **Step 4: Replace month_artists query (line ~1478)**

Same as week_artists but `'-30 days'`.

- [ ] **Step 5: Replace month_albums query (line ~1491)**

Same as week_albums but `'-30 days'`.

- [ ] **Step 6: Replace month_songs query (line ~1506)**

Same as week_songs but `'-30 days'`.

- [ ] **Step 7: Run full test suite**

```bash
uv run pytest -v
```

Expected: all green.

- [ ] **Step 8: Run full check**

```bash
hk check
```

- [ ] **Step 9: Commit**

```bash
git add src/lytter/app.py
git commit -m "feat: merge key variants in recent_stats week/month queries"
```

---

## Task 8: Update `meta_updater.py` and `duration_updater.py`

**Files:**

- Modify: `src/lytter/meta_updater.py`
- Modify: `src/lytter/duration_updater.py`

These are internal batch scripts, not tested via the endpoint suite. Update the GROUP BY
queries so they return deduplicated canonical names to avoid fetching metadata twice for
the same artist/track key.

- [ ] **Step 1: No import changes needed for `meta_updater.py`**

`normalize_name` is not called directly — keys are read from the DB columns. Existing
imports are unchanged.

- [ ] **Step 2: Replace `_get_artists` force branch**

```python
if force:
    cursor.execute("""
        SELECT
            (SELECT m2.artist FROM musiclibrary m2
             WHERE m2.artist_key = m.artist_key
             GROUP BY m2.artist ORDER BY COUNT(*) DESC LIMIT 1) AS artist,
            COUNT(*) AS plays
        FROM musiclibrary m
        GROUP BY m.artist_key
        ORDER BY plays DESC
    """)
```

- [ ] **Step 3: Replace `_get_artists` retry_empty branch**

```python
elif retry_empty:
    cursor.execute("""
        SELECT canonical_artist, plays
        FROM (
            SELECT
                (SELECT m2.artist FROM musiclibrary m2
                 WHERE m2.artist_key = m.artist_key
                 GROUP BY m2.artist ORDER BY COUNT(*) DESC LIMIT 1) AS canonical_artist,
                m.artist_key,
                COUNT(*) AS plays
            FROM musiclibrary m
            GROUP BY m.artist_key
        ) sub
        LEFT JOIN artist_genres ag ON ag.artist = sub.canonical_artist
        WHERE ag.artist IS NULL OR ag.tags = '[]'
        ORDER BY plays DESC
    """)
```

- [ ] **Step 4: Replace `_get_artists` default branch**

```python
else:
    cursor.execute("""
        SELECT canonical_artist, plays
        FROM (
            SELECT
                (SELECT m2.artist FROM musiclibrary m2
                 WHERE m2.artist_key = m.artist_key
                 GROUP BY m2.artist ORDER BY COUNT(*) DESC LIMIT 1) AS canonical_artist,
                m.artist_key,
                COUNT(*) AS plays
            FROM musiclibrary m
            GROUP BY m.artist_key
        ) sub
        LEFT JOIN artist_genres ag ON ag.artist = sub.canonical_artist
        WHERE ag.artist IS NULL
        ORDER BY plays DESC
    """)
```

- [ ] **Step 5: No import changes needed for `duration_updater.py`**

`normalize_name` is not called directly — keys are read from the DB columns. Existing
imports are unchanged.

- [ ] **Step 6: Replace `_get_tracks` force branch**

```python
if force:
    cursor.execute("""
        SELECT
            (SELECT m2.artist FROM musiclibrary m2
             WHERE m2.artist_key = m.artist_key
             GROUP BY m2.artist ORDER BY COUNT(*) DESC LIMIT 1) AS artist,
            (SELECT m2.track FROM musiclibrary m2
             WHERE m2.artist_key = m.artist_key AND m2.track_key = m.track_key
             GROUP BY m2.track ORDER BY COUNT(*) DESC LIMIT 1) AS track,
            MAX(m.track_mbid) AS track_mbid
        FROM musiclibrary m
        GROUP BY m.artist_key, m.track_key
    """)
```

- [ ] **Step 7: Replace `_get_tracks` retry_failed branch**

```python
elif retry_failed:
    cursor.execute("""
        SELECT canonical_artist, canonical_track, track_mbid
        FROM (
            SELECT
                (SELECT m2.artist FROM musiclibrary m2
                 WHERE m2.artist_key = m.artist_key
                 GROUP BY m2.artist ORDER BY COUNT(*) DESC LIMIT 1) AS canonical_artist,
                (SELECT m2.track FROM musiclibrary m2
                 WHERE m2.artist_key = m.artist_key AND m2.track_key = m.track_key
                 GROUP BY m2.track ORDER BY COUNT(*) DESC LIMIT 1) AS canonical_track,
                m.artist_key,
                m.track_key,
                MAX(m.track_mbid) AS track_mbid
            FROM musiclibrary m
            GROUP BY m.artist_key, m.track_key
        ) sub
        LEFT JOIN track_durations td
            ON td.artist = sub.canonical_artist AND td.track = sub.canonical_track
        WHERE td.artist IS NULL OR td.duration_ms IS NULL
    """)
```

- [ ] **Step 8: Replace `_get_tracks` default branch**

```python
else:
    cursor.execute("""
        SELECT canonical_artist, canonical_track, track_mbid
        FROM (
            SELECT
                (SELECT m2.artist FROM musiclibrary m2
                 WHERE m2.artist_key = m.artist_key
                 GROUP BY m2.artist ORDER BY COUNT(*) DESC LIMIT 1) AS canonical_artist,
                (SELECT m2.track FROM musiclibrary m2
                 WHERE m2.artist_key = m.artist_key AND m2.track_key = m.track_key
                 GROUP BY m2.track ORDER BY COUNT(*) DESC LIMIT 1) AS canonical_track,
                m.artist_key,
                m.track_key,
                MAX(m.track_mbid) AS track_mbid
            FROM musiclibrary m
            GROUP BY m.artist_key, m.track_key
        ) sub
        LEFT JOIN track_durations td
            ON td.artist = sub.canonical_artist AND td.track = sub.canonical_track
        WHERE td.artist IS NULL
    """)
```

- [ ] **Step 9: Update return in `_get_tracks` to use new column names**

The return at the end of `_get_tracks` is:

```python
return [(row[0], row[1], row[2] or None) for row in cursor.fetchall()]
```

This is unchanged — column indices 0, 1, 2 still map to artist, track, track_mbid.

- [ ] **Step 10: Run full test suite**

```bash
uv run pytest -v
```

Expected: all green.

- [ ] **Step 11: Run full check**

```bash
hk check
```

- [ ] **Step 12: Commit**

```bash
git add src/lytter/meta_updater.py src/lytter/duration_updater.py
git commit -m "feat: deduplicate artists/tracks by key in meta and duration updaters"
```
