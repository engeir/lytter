# Front Page Redesign — "Recently"

**Date:** 2026-05-24

## Goal

Transform the front page from an all-time statistics dashboard into a recency-focused
page. Move heavy analytics to the all-time page. Improve mobile nav.

---

## 1. Front Page (`/`) — "Recently"

### Remove

- Stat cards row (total scrobbles, unique artists, tracks, albums, listening time,
  current streak, longest streak)
- Listening Timeline chart
- Listening Streaks chart
- Top Artists / Albums / Songs all-time tabs

### Keep

- Currently Playing card (conditional on now-playing)
- Activity Calendar (HTMX)
- On This Day (HTMX)
- Recent Favorites (past week + month top lists, HTMX)

### Add — Recent Plays card

- HTMX-loaded via `GET /html/recent-plays`
- Queries last 30 scrobbles ordered by `timestamp DESC`
- Each row: `track · artist` + right-aligned relative time (e.g. "2m ago", "3h ago", "2d
  ago")
- Track and artist names link to their `/song/` and `/artist/` pages
- Fixed-height container (~320px); CSS `linear-gradient(transparent, <bg-color>)`
  overlay fades bottom
- No "show more" — purely decorative fade

### Layout

```
[ Currently Playing (if active) ]
[ Recent Plays          ] [ Activity Calendar ]
[ On This Day           ] [ Recent Favorites  ]
```

---

## 2. All-Time Page (`/all-time`)

### Add at top

Stat cards row (same 7 cards currently on front page): total scrobbles, unique artists,
unique tracks, unique albums, listening time, current streak, longest streak.

Backend: extract stat-gathering logic from `index()` into a shared helper so both routes
can use it without duplication.

### Add

- **Listening Timeline chart** (currently on front page, year-scoped)
  - Expand to support all-time range: remove or make optional the current year filter
  - Reuse existing `/charts/listening-timeline` endpoint; add `range` query param
    (`year` default for backwards compat, `all` for full history)
- **Listening Streaks chart** (moved from front page, HTMX `/html/streak-history`)

### Keep

Existing content: accumulated listens chart, time spent chart, artist/album/song tabs.

---

## 3. Responsive Nav

Current nav (`base.html`) has no mobile menu — links are hidden on small screens.

### Change

Replace bare `<div class="navbar-nav">` with a Bootstrap 5 collapsible navbar:

- Add `<button class="navbar-toggler">` (hamburger icon)
- Wrap links in `<div class="collapse navbar-collapse">`
- Search bar collapses into the menu on mobile (or moves below links)

No custom JS needed — Bootstrap's `navbar-toggler` handles collapse via
`data-bs-toggle`.

---

## 4. Backend Changes

### New endpoint

```
GET /html/recent-plays
```

- Queries `musiclibrary` for last 30 scrobbles: `ORDER BY timestamp DESC LIMIT 30`
- Computes relative time string from Unix `timestamp` field
- Returns HTML fragment rendered from new `_recent_plays.html` partial

### Modified endpoint

```
GET /charts/listening-timeline?range=all   (new)
GET /charts/listening-timeline             (unchanged — still year-scoped)
```

The `range=all` path removes the `WHERE timestamp >= <year-start>` filter (or
equivalent).

### Shared helper

Extract the 7 stat queries from `index()` into `_get_dashboard_stats(conn) -> dict` so
`alltime()` can call it too without duplication.

---

## 5. Files Touched

| File                                      | Change                                                                                        |
| ----------------------------------------- | --------------------------------------------------------------------------------------------- |
| `src/lytter/templates/index.html`         | Remove cards/charts/tabs; add Recent Plays card                                               |
| `src/lytter/templates/alltime.html`       | Add stat cards + timeline + streaks                                                           |
| `src/lytter/templates/base.html`          | Responsive navbar                                                                             |
| `src/lytter/templates/_recent_plays.html` | New HTMX fragment                                                                             |
| `src/lytter/app.py`                       | New `/html/recent-plays`; extend `/charts/listening-timeline`; extract `_get_dashboard_stats` |

---

## Out of Scope

- Pagination or infinite scroll for recent plays
- Redesigning other pages (genre, yearly, artist, etc.)
- Dark/light theme changes
