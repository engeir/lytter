# Enhanced Bump Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or superpowers:executing-plans
> to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the noisy ranking evolution chart on the yearly stats page with a
clean enhanced bump chart — spline curves, marker size proportional to play count, top 8
by yearly total, line gaps for absent months, and right-side per-item labels.

**Architecture:** Single-file frontend change in `src/lytter/templates/yearly.html`.
Replace `renderEvolutionChart()` with `renderBumpChart()`. Reuse the existing
`/api/yearly/evolution` endpoint; fetch `top_n=15` then client-side select top 8 by
total yearly plays. No backend changes.

**Tech Stack:** Plotly.js (already loaded on page), vanilla JS, Jinja2 template.

---

### Task 1: Update title, API param, and call site

**Files:**

- Modify: `src/lytter/templates/yearly.html:129` (card title)
- Modify: `src/lytter/templates/yearly.html:216` (top_n param)
- Modify: `src/lytter/templates/yearly.html:219` (call site rename)

- [ ] **Step 1: Update card title**

In `src/lytter/templates/yearly.html` line 129, change:

```html
<h5 class="card-title">📈 Monthly Top 3 Ranking Evolution</h5>
```

to:

```html
<h5 class="card-title">📈 Monthly Ranking Evolution</h5>
```

- [ ] **Step 2: Update chart container heights from 600px to 500px**

In `src/lytter/templates/yearly.html` lines 155, 158, and 161, change all three
occurrences of:

```html
<div id="artists-evolution-chart" style="height: 600px"></div>
```

```html
<div id="albums-evolution-chart" style="height: 600px"></div>
```

```html
<div id="songs-evolution-chart" style="height: 600px"></div>
```

to `height: 500px` in each.

- [ ] **Step 3: Update API call and call site**

In `src/lytter/templates/yearly.html` lines 215–222, replace the entire
`loadEvolutionForType` function:

```javascript
function loadEvolutionForType(itemType) {
  fetch(`/api/yearly/evolution?year=${currentYear}&item_type=${itemType}&top_n=15`)
    .then((response) => response.json())
    .then((data) => {
      renderBumpChart(data, itemType);
    })
    .catch((error) => console.error(`Error loading ${itemType} evolution:`, error));
}
```

- [ ] **Step 4: Verify page loads without JS errors**

Start server: `mise run r` Open `http://localhost:8000/yearly` in browser. Open browser
dev tools → Console tab. Expected: no `renderBumpChart is not defined` or similar errors
(the function call site now points to a function we haven't written yet — the fetch will
succeed but the then-callback will throw; that's acceptable and expected at this step).

- [ ] **Step 5: Commit**

```bash
git add src/lytter/templates/yearly.html
git commit -m "refactor(yearly): rename evolution chart title, bump top_n to 15, shrink height to 500px"
```

---

### Task 2: Write `renderBumpChart()`

**Files:**

- Modify: `src/lytter/templates/yearly.html:224–451` (replace `renderEvolutionChart`
  entirely)

- [ ] **Step 1: Delete `renderEvolutionChart` and replace with `renderBumpChart`**

In `src/lytter/templates/yearly.html`, replace lines 224–451 (the full
`renderEvolutionChart` function including the `setTimeout` legend-hover block at the
end) with the following complete function:

```javascript
function renderBumpChart(data, itemType) {
  if (!data.dates || data.dates.length === 0) {
    return;
  }

  const monthNames = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ];

  // Select top 8 items by total yearly plays
  const totals = {};
  data.items.forEach((item) => {
    totals[item] = data.data[item].reduce((sum, v) => sum + v, 0);
  });
  const top8 = [...data.items].sort((a, b) => totals[b] - totals[a]).slice(0, 8);

  // Marker scaling: map play count to [BASE_SIZE, MAX_SIZE]
  let maxPlays = 1;
  top8.forEach((item) => {
    data.data[item].forEach((plays) => {
      if (plays > maxPlays) maxPlays = plays;
    });
  });
  const BASE_SIZE = 6;
  const MAX_SIZE = 18;
  const scale = (MAX_SIZE - BASE_SIZE) / maxPlays;

  // Compute per-month ranks against ALL fetched items (not just top 8)
  const monthRanks = {};
  top8.forEach((item) => {
    monthRanks[item] = [];
  });

  for (let mIdx = 0; mIdx < 12; mIdx++) {
    const sorted = [...data.items]
      .map((it) => ({ item: it, plays: data.data[it][mIdx] }))
      .sort((a, b) => b.plays - a.plays);
    top8.forEach((item) => {
      monthRanks[item].push(sorted.findIndex((x) => x.item === item) + 1);
    });
  }

  const colors = [
    "#58a6ff",
    "#ff6b6b",
    "#4ecdc4",
    "#ffd93d",
    "#ff9ff3",
    "#a8e6cf",
    "#ffaaa5",
    "#b4a7d6",
  ];

  // Build traces — null y-value for months with 0 plays (creates visible gap)
  const traces = top8.map((item, i) => {
    const yVals = [];
    const sizes = [];
    const hoverText = [];

    for (let mIdx = 0; mIdx < 12; mIdx++) {
      const plays = data.data[item][mIdx];
      const rank = monthRanks[item][mIdx];
      if (plays === 0) {
        yVals.push(null);
        sizes.push(0);
      } else {
        yVals.push(rank);
        sizes.push(Math.round(BASE_SIZE + plays * scale));
      }
      hoverText.push(`${monthNames[mIdx]}<br>Rank: #${rank}<br>Plays: ${plays}`);
    }

    const displayName = item.length > 30 ? item.substring(0, 27) + "..." : item;
    return {
      x: monthNames,
      y: yVals,
      name: displayName,
      type: "scatter",
      mode: "lines+markers",
      connectgaps: false,
      line: {
        shape: "spline",
        color: colors[i % colors.length],
        width: 3,
      },
      marker: {
        size: sizes,
        color: colors[i % colors.length],
        line: { color: "#161b22", width: 2 },
      },
      hovertext: hoverText,
      hoverinfo: "text",
      showlegend: false,
    };
  });

  // Build right-side annotations (one label per item at its last non-null month)
  // Track used ranks to offset overlapping labels
  const rankOffsets = {};
  const annotations = top8
    .map((item, i) => {
      let lastMIdx = -1;
      let lastRank = null;
      for (let mIdx = 11; mIdx >= 0; mIdx--) {
        if (data.data[item][mIdx] > 0) {
          lastMIdx = mIdx;
          lastRank = monthRanks[item][mIdx];
          break;
        }
      }
      if (lastMIdx === -1) return null;

      if (!rankOffsets[lastRank]) rankOffsets[lastRank] = 0;
      const yOffset = rankOffsets[lastRank] * 0.4;
      rankOffsets[lastRank]++;

      const labelName = item.length > 25 ? item.substring(0, 22) + "..." : item;
      return {
        x: monthNames[lastMIdx],
        y: lastRank + yOffset,
        text: labelName,
        xanchor: "left",
        yanchor: "middle",
        xshift: 12,
        showarrow: false,
        font: { color: colors[i % colors.length], size: 10 },
      };
    })
    .filter(Boolean);

  const layout = {
    paper_bgcolor: "#161b22",
    plot_bgcolor: "#161b22",
    font: { color: "#f0f6fc", size: 12 },
    xaxis: {
      gridcolor: "#30363d",
      color: "#f0f6fc",
      title: "Month",
    },
    yaxis: {
      gridcolor: "#30363d",
      color: "#f0f6fc",
      title: "Rank",
      autorange: false,
      tickmode: "linear",
      tick0: 1,
      dtick: 1,
      range: [8.5, 0.5],
    },
    hovermode: "closest",
    showlegend: false,
    annotations: annotations,
    margin: { l: 60, r: 180, t: 20, b: 60 },
  };

  const chartId = `${itemType}-evolution-chart`;
  Plotly.newPlot(chartId, traces, layout, { responsive: true, displayModeBar: false });

  const chartElement = document.getElementById(chartId);

  chartElement.on("plotly_hover", function (eventData) {
    const hoveredIndex = eventData.points[0].curveNumber;
    const update = {
      "line.width": [],
      "line.color": [],
      "marker.size": [],
      opacity: [],
    };
    traces.forEach((trace, index) => {
      if (index === hoveredIndex) {
        update["line.width"].push(5);
        update["line.color"].push(colors[index % colors.length]);
        update["marker.size"].push(trace.marker.size.map((s) => (s ? s * 1.3 : 0)));
        update.opacity.push(1);
      } else {
        update["line.width"].push(2);
        update["line.color"].push(colors[index % colors.length]);
        update["marker.size"].push(trace.marker.size);
        update.opacity.push(0.3);
      }
    });
    Plotly.restyle(chartId, update);
  });

  chartElement.on("plotly_unhover", function () {
    const update = {
      "line.width": traces.map(() => 3),
      "line.color": traces.map((t, i) => colors[i % colors.length]),
      "marker.size": traces.map((t) => t.marker.size),
      opacity: traces.map(() => 1),
    };
    Plotly.restyle(chartId, update);
  });

  chartElement.on("plotly_legendclick", function () {
    return false;
  });
  chartElement.on("plotly_legenddoubleclick", function () {
    return false;
  });
}
```

- [ ] **Step 2: Run `hk check`**

```bash
hk check
```

Expected: passes (djlint may reformat the JS block; that's fine — accept any
auto-formatting).

- [ ] **Step 3: Open browser and verify chart renders**

Open `http://localhost:8000/yearly`. Check Artists tab:

- Chart renders (no blank div)
- Lines are curved (spline), not jagged
- Markers vary in size month-to-month
- Right-side colored labels visible (no external legend box)
- Y-axis shows ranks 1–8, rank 1 at top

Switch to Albums and Songs tabs — same checks.

- [ ] **Step 4: Verify one-month-wonder gap behavior**

If any item in the data has 0 plays in some months, its line should show a visible break
(gap) for those months rather than connecting through zero. Check by hovering near a gap
month — the hover tooltip should not appear for that point.

(If all items have plays every month in your test data, this is not testable but the
logic is correct by construction — `null` y-values with `connectgaps: false`.)

- [ ] **Step 5: Verify hover highlighting**

Hover over a line — hovered line should brighten (thicker), others should fade (opacity
0.3). Move cursor away — all lines return to full opacity and width 3.

- [ ] **Step 6: Verify year-change reloads chart**

Change the year selector. Charts should reload with new data. No JS errors in console.

- [ ] **Step 7: Commit**

```bash
git add src/lytter/templates/yearly.html
git commit -m "feat(yearly): replace spaghetti ranking chart with enhanced bump chart

- Top 8 items by total yearly plays (was: all items hitting monthly top 3)
- Spline curves instead of jagged lines
- Marker size proportional to play count (rank + volume visible simultaneously)
- connectgaps: false — zero-play months show as visible line gaps
- Direct right-side per-item color-matched labels, no external legend"
```

---

## Self-Review Checklist

- [x] Spec: spline lines → `line.shape: 'spline'` ✓
- [x] Spec: marker size ∝ play count → `BASE_SIZE + plays * scale` ✓
- [x] Spec: top 8 by yearly total → sum + sort + slice(0,8) ✓
- [x] Spec: ranks computed against all 15 fetched items → `sorted` uses `data.items` not
      `top8` ✓
- [x] Spec: connectgaps: false + null for 0-play months → explicit null push ✓
- [x] Spec: right-side annotations with color + collision offset → `rankOffsets` dict ✓
- [x] Spec: hover highlight preserved → plotly_hover/unhover handlers ✓
- [x] Spec: legend click suppressed → return false handlers ✓
- [x] Spec: y-axis range [8.5, 0.5] → layout.yaxis.range ✓
- [x] Spec: height 500px → div already uses inline style, update needed? Check
      yearly.html:155–161 — `style="height: 600px"`. Update to 500px.
- [x] Spec: margin r: 180 → layout.margin ✓
- [x] Spec: title update → Task 1 Step 1 ✓
- [x] Spec: top_n=15 → Task 1 Step 2 ✓

**Gap found:** Chart container divs still have `height: 600px`. Spec says 500px. Add fix
to Task 1.
