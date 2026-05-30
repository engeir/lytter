# Name Normalization Design

**Date:** 2026-05-30 **Status:** Approved

## Problem

Last.fm and other platforms emit inconsistent capitalization and formatting for artist,
album, and track names. "Angine de poitrine" and "Angine de Poitrine" appear as two
distinct entries in all queries, splitting play counts and inflating unique-count stats.

## Scope

Covers all three fields: artist, album, track. Handles:

- Case differences ("Angine de poitrine" vs "Angine de Poitrine")
- Unicode form differences (NFC vs NFD)
- Diacritic stripping variants ("Sigur Rós" vs "Sigur Ros")
- Featured-artist formatting on tracks ("feat.", "ft.", "featuring", with or without
  parens/brackets)
- Ampersand vs "and"

Intentionally excluded from v1:

- "The" prefix stripping (too many false positives)
- Punctuation normalization like "AC/DC" vs "ACDC" (deferred)
- MBID-based conflict detection (MBIDs too sparse/flaky to be useful)

## Approach: Separate key columns (Option B)

Raw strings preserved in `artist`, `album`, `track` columns for display. Three new
columns store normalized keys for grouping:

- `artist_key TEXT`
- `album_key TEXT`
- `track_key TEXT`

Keys are deterministically recomputable from raw strings, so rule changes only require a
backfill — no data loss possible.

## Normalization Pipeline

Function signature: `normalize_name(s: str, field: str) -> str`

Applied in order:

1. **NFC unicode normalization** — `unicodedata.normalize("NFC", s)`
2. **Whitespace** — `strip()` + collapse internal runs to single space
3. **Lowercase** — `s.lower()`
4. **Diacritic stripping** — NFD decompose, drop Mn-category chars (reuses existing
   `_strip_accents()`)
5. **Feat. normalization (track only)** — collapse all variants to `feat.`:
   - Parenthesized/bracketed: `[\(\[]\s*(?:feat\.?|ft\.?|featuring)\s+([^\)\]]+)[\)\]]`
     → `feat. \1`
   - Bare: `\b(?:ft\.?|featuring)\b` → `feat.`
6. **Ampersand** — `&` → `and`

`field` parameter enables track-only rules (step 5). Artist and album skip it.

## Schema Changes

```sql
ALTER TABLE musiclibrary ADD COLUMN artist_key TEXT;
ALTER TABLE musiclibrary ADD COLUMN album_key  TEXT;
ALTER TABLE musiclibrary ADD COLUMN track_key  TEXT;

CREATE INDEX IF NOT EXISTS idx_artist_key       ON musiclibrary(artist_key);
CREATE INDEX IF NOT EXISTS idx_artist_album_key ON musiclibrary(artist_key, album_key);
CREATE INDEX IF NOT EXISTS idx_artist_track_key ON musiclibrary(artist_key, track_key);
```

Added in `init_db()` using `IF NOT EXISTS` / existence check so it is idempotent on
repeated startup.

`track_durations` and `lyrics` tables keep raw `(artist, track)` PKs — they are joined
through `musiclibrary` at query time and do not need key columns.

## Migration / Backfill

`backfill_keys(conn)` called from `init_db()`:

```python
def backfill_keys(conn):
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, artist, album, track FROM musiclibrary WHERE artist_key IS NULL"
    )
    for row_id, artist, album, track in cursor.fetchall():
        cursor.execute(
            "UPDATE musiclibrary SET artist_key=?, album_key=?, track_key=? WHERE id=?",
            (
                normalize_name(artist, "artist"),
                normalize_name(album, "album"),
                normalize_name(track, "track"),
                row_id,
            ),
        )
    conn.commit()
```

Only processes NULL rows — effectively a no-op after first run.

## Query Pattern

All `GROUP BY artist` → `GROUP BY artist_key`. Display name picked as the most-frequent
raw value per key group via correlated subquery:

```sql
SELECT
    (SELECT artist FROM musiclibrary m2
     WHERE m2.artist_key = m.artist_key
     GROUP BY m2.artist ORDER BY COUNT(*) DESC LIMIT 1) AS artist,
    artist_key,
    COUNT(*) AS plays
FROM musiclibrary m
GROUP BY artist_key
ORDER BY plays DESC
LIMIT 50
```

Same pattern for `(artist_key, album_key)` and `(artist_key, track_key)`.

## Affected Files

| File                             | What changes                                                                                                              |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `src/lytter/app.py`              | Add `normalize_name()`, update `init_db()`, update `backfill_keys()`, update all GROUP BY query sites, update INSERT path |
| `src/lytter/gap_checker.py`      | Update INSERT path to compute keys                                                                                        |
| `src/lytter/meta_updater.py`     | Update GROUP BY query sites                                                                                               |
| `src/lytter/duration_updater.py` | Update GROUP BY query sites                                                                                               |
| `src/lytter/db_status.py`        | Update COUNT(DISTINCT) queries                                                                                            |

## Query Sites to Update

Confirmed via grep:

- `app.py`: lines 620, 625, 631, 1225, 1239, 1256, 1273, 1440, 1454, 1468, 1482, 1496
- `db_status.py`: line 32
- `meta_updater.py`: lines 26, 35, 45
- `duration_updater.py`: lines 20, 29, 38

## Non-Goals

- Manual alias overrides (no alias table)
- UI to review/approve merges
- Punctuation normalization (deferred to v2)
- "The" prefix handling (excluded permanently unless needed)
