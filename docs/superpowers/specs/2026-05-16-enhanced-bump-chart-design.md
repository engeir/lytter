# Enhanced Monthly Ranking Bump Chart

**Date:** 2026-05-16
**Status:** Approved

## Problem

The current "Monthly Top 3 Ranking Evolution" plot on the yearly stats page is noisy and hard
to read. Key issues:
- Too many items (15+) creates spaghetti lines
- Rank encodes no magnitude — being #1 with 10 plays looks identical to #1 with 100 plays
- Y-axis inversion is counterintuitive
- `top_n=3` picks items that hit any month's top 3, resulting in many low-volume items

## Goal

Replace with a cleaner bump chart that preserves the core value: seeing the full year's
evolution at a glance, spotting one-month wonders vs. consistent top performers.

## Design

### Item Selection

Change from "items that appeared in any month's top N" to **top 8 items by total yearly plays**:

1. Fetch `/api/yearly/evolution?year=X&item_type=Y&top_n=15` (increased from 3)
2. Client-side: for each item, sum all 12 monthly play counts → yearly total
3. Sort by yearly total descending, take top 8
4. Render only those 8 items

This surfaces consistent performers and naturally limits spaghetti.

### Visual Improvements

| Property | Current | New |
|----------|---------|-----|
| Line shape | Linear (jagged) | Spline (curved) |
| Marker size | Fixed 8px | Proportional to play count |
| Item count | All that hit top 3 any month (15+) | Top 8 by yearly total |
| Y-axis range | 1–15 | 1–8 with padding |
| Line gaps | `connectgaps: true` (hides absence) | `connectgaps: false` (gaps show 0-play months) |
| Legend | External right-side legend box | Direct right-side annotations per line |

**Marker sizing:** `size = BASE_SIZE + plays * SCALE_FACTOR`. BASE_SIZE ~6px. SCALE_FACTOR
chosen so the largest marker in a given chart is ~18px. Computed per-render from the max
play count across all months/items in that tab.

**Line gaps:** When an item has 0 plays in a month, its data point is `null`. Plotly with
`connectgaps: false` renders this as a visible break — one-month wonders appear as isolated
dots surrounded by gaps.

**Annotations:** Right-side item name labels placed at each item's December (or last non-null
month) data point. Font color matches line color. If two items end at the same rank, offset
the annotations by ±0.3 rank units to prevent overlap.

### Controls & Interaction

Hover tooltip: `{MonthName}\nRank: #{rank}\nPlays: {count}`

Hover highlighting (existing behavior preserved):
- Hovered line: `width: 5`, `opacity: 1`
- Other lines: `width: 2`, `opacity: 0.3`

Legend click/double-click continue to be suppressed (existing behavior).

### Data Flow

```
Year selector change
  → loadEvolution()
    → loadEvolutionForType('artists' | 'albums' | 'songs')
      → GET /api/yearly/evolution?year=X&item_type=Y&top_n=15
        → renderBumpChart(data, itemType)
          → compute yearly totals per item
          → select top 8 by total
          → compute per-month ranks (against all 15 fetched items, not just top 8)
          → build Plotly traces with spline + variable markers + null gaps
          → build annotations for right-side labels
          → Plotly.newPlot(...)
          → attach hover/unhover event listeners
```

Note: ranks are computed against all 15 fetched items, not just the top 8 shown. This
preserves accurate ranking context (an item shown at rank #3 is truly #3 among all tracked
items, not just #3 out of 8).

### Layout

```
paper_bgcolor / plot_bgcolor: '#161b22'  (unchanged)
height: 500px                             (was 600px)
margin: { l: 60, r: 180, t: 20, b: 60 }  (r increased for annotations)
yaxis: { range: [8.5, 0.5], autorange: false }  (1 at top, 8 at bottom)
```

## Scope

**Changes:** `src/lytter/templates/yearly.html` only.
- Replace `renderEvolutionChart()` with `renderBumpChart()`
- Update API call `top_n=3` → `top_n=15`
- Update card title from "Monthly Top 3 Ranking Evolution" to "Monthly Ranking Evolution"

**No changes:** `app.py`, CSS, other templates, database.

## Non-Goals

- Animating the chart (rejected in favor of full-year overview)
- Backend API changes
- Adding new endpoints
- Changing the tab structure (artists / albums / songs tabs remain)
