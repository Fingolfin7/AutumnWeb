# Charts Implementation Plan

## Overview

Add 8 new chart types to the Autumn time tracking application and refactor the charts codebase for maintainability.

## New Charts to Implement

| Chart | Category | Data Source | Purpose |
|-------|----------|-------------|---------|
| Treemap | Hierarchy | tally + structure | Context → Project → SubProject breakdown by time |
| Stacked Area | Trends | sessions | Cumulative time trends across projects |
| Status Donut | Summary | projects | Breakdown by project status |
| Context Comparison | Summary | tally by context | Compare time across contexts |
| Session Histogram | Analysis | sessions | Distribution of session durations |
| Cumulative Line | Trends | sessions | Running total of hours over time |
| Tag Bubble | Analysis | projects + tags | Bubbles sized by time per tag |
| Radar | Analysis | projects | Multi-dimensional project comparison |

---

## Phase 1: Refactor File Structure ✅ COMPLETE

### Current Structure
```
core/static/core/js/
└── charts.js (~1025 lines, monolithic)  # OLD - can be removed
```

### New Structure ✅
```
core/static/core/js/
├── charts/
│   ├── core.js          # Utilities, data fetching, render orchestration
│   ├── basic.js         # Pie, Bar, Line, Scatter (standard Chart.js)
│   ├── time.js          # Calendar, Heatmap (matrix-based)
│   ├── hierarchy.js     # Treemap (hierarchical data)
│   ├── trends.js        # Stacked Area, Cumulative Line
│   ├── analysis.js      # Histogram, Radar, Tag Bubble
│   └── wordcloud.js     # Wordcloud (uses separate library)
└── charts.js            # OLD - kept for reference, not loaded
```

### Module Dependencies
```
core.js (load first)
   ↓
basic.js, time.js, hierarchy.js, trends.js, analysis.js, wordcloud.js (load in parallel)
```

### core.js Contents
- `generateRandomColor()`
- `fillDates()`
- `getChartUnit()`
- `format_date()`
- `countWeekdays()`
- `clearChart()`
- `get_project_data()`
- `showLoading()`, `hideLoading()`, `showEmpty()`, `hideEmpty()`
- `render()` orchestration
- `chartFns` registry (populated by other modules via `window.AutumnCharts`)
- Document ready initialization

### Tasks
- [x] Create `charts/` directory structure
- [x] Extract shared utilities to `core.js`
- [x] Move existing charts to appropriate modules
- [x] Update `charts.html` to load new script files
- [x] Update `static/core/js/` copy (for collectstatic)
- [ ] Test that existing charts still work

---

## Phase 2: Add External Dependencies ✅ COMPLETE

### Required Libraries

| Library | Version | Purpose | CDN |
|---------|---------|---------|-----|
| chartjs-chart-treemap | 2.3.x | Treemap charts | jsdelivr |
| d3-hierarchy | 3.x | Sunburst calculations | Already have D3 v7 |

### Update charts.html ✅
```html
<!-- After existing Chart.js includes -->
<script src="https://cdn.jsdelivr.net/npm/chartjs-chart-treemap@2.3.0"></script>
```

### Tasks
- [x] Add treemap plugin CDN to charts.html
- [x] Verify D3.js v7 is sufficient for sunburst

---

## Phase 3: Backend API Updates ✅ COMPLETE

### New Endpoints Created

#### 1. Hierarchy Data Endpoint
**URL:** `/api/hierarchy/`
**Purpose:** Returns nested Context → Project → SubProject structure with times
**Response:**
```json
{
  "name": "All",
  "children": [
    {
      "name": "Work",
      "context_id": 1,
      "children": [
        {
          "name": "Project A",
          "project_id": 1,
          "total_time": 120,
          "children": [
            {"name": "SubProject X", "subproject_id": 1, "total_time": 60},
            {"name": "SubProject Y", "subproject_id": 2, "total_time": 60}
          ]
        }
      ]
    }
  ]
}
```

#### 2. Context Tally Endpoint
**URL:** `/api/tally_by_context/`
**Purpose:** Aggregate time by context
**Response:**
```json
[
  {"name": "Work", "context_id": 1, "total_time": 500},
  {"name": "Personal", "context_id": 2, "total_time": 300}
]
```

#### 3. Status Tally Endpoint
**URL:** `/api/tally_by_status/`
**Purpose:** Aggregate project count/time by status
**Response:**
```json
[
  {"status": "active", "count": 5, "total_time": 400},
  {"status": "complete", "count": 10, "total_time": 800}
]
```

#### 4. Tag Tally Endpoint
**URL:** `/api/tally_by_tags/`
**Purpose:** Aggregate time by tag
**Response:**
```json
[
  {"name": "python", "tag_id": 1, "total_time": 300, "project_count": 3},
  {"name": "frontend", "tag_id": 2, "total_time": 200, "project_count": 2}
]
```

### Tasks
- [x] Add `hierarchy` endpoint to `core/api.py`
- [x] Add `tally_by_context` endpoint
- [x] Add `tally_by_status` endpoint
- [x] Add `tally_by_tags` endpoint
- [x] Add `projects_with_stats` endpoint (for radar chart)
- [x] Add URL routes to `core/urls.py`
- [x] Add hidden inputs to `charts.html` for new endpoints

---

## Phase 4: Implement Hierarchy Charts

### 4.1 Treemap

**File:** `charts/hierarchy.js`

**Function:** `treemap_chart(data, ctx)`

**Features:**
- Nested rectangles: Context → Project → SubProject
- Color by context (top level)
- Size by total_time
- Click to drill down (optional)
- Tooltip shows: name, time, percentage of parent

**Chart.js Config:**
```javascript
{
  type: 'treemap',
  data: {
    datasets: [{
      tree: hierarchyData,
      key: 'total_time',
      groups: ['context', 'project', 'subproject'],
      backgroundColor: (ctx) => colorByDepth(ctx),
      labels: { display: true, formatter: (ctx) => ctx.raw.g }
    }]
  }
}
```

### Tasks
- [x] Implement `treemap_chart()` function
- [x] Add to chartFns registry
- [x] Add dropdown options in charts.html
- [ ] Test with real data

---

## Phase 5: Implement Trend Charts

### 5.1 Stacked Area

**File:** `charts/trends.js`

**Function:** `stacked_area_chart(data, ctx)`

**Features:**
- X-axis: time (like line chart)
- Y-axis: hours
- Areas stacked by project
- Fill with transparency
- Same color scheme as line chart

**Chart.js Config:**
```javascript
{
  type: 'line',
  data: { datasets }, // with fill: 'stack' or fill: '-1'
  options: {
    scales: { y: { stacked: true } },
    plugins: { filler: { propagate: true } }
  }
}
```

### 5.2 Cumulative Line

**File:** `charts/trends.js`

**Function:** `cumulative_line_chart(data, ctx)`

**Features:**
- X-axis: time
- Y-axis: cumulative hours (running total)
- Single line (or one per project if filtered)
- Shows growth over time
- Tooltip shows: date, cumulative total, daily addition

**Implementation:**
- Sort sessions by date
- Calculate running sum
- Plot as line chart

### Tasks
- [x] Implement `stacked_area_chart()` function
- [x] Implement `cumulative_line_chart()` function
- [x] Add to chartFns registry
- [x] Add dropdown options
- [ ] Test with date ranges

---

## Phase 6: Implement Summary Charts

### 6.1 Status Donut

**File:** `charts/basic.js` (extension of existing pie)

**Function:** `status_donut_chart(data, ctx)`

**Features:**
- Donut chart showing project status distribution
- Segments: Active, Paused, Complete, Archived
- Fixed color scheme (green=active, yellow=paused, blue=complete, gray=archived)
- Show count and total time

### 6.2 Context Comparison Bar

**File:** `charts/basic.js`

**Function:** `context_bar_chart(data, ctx)`

**Features:**
- Horizontal bar chart
- One bar per context
- Sorted by total time descending
- Color coded by context

### Tasks
- [x] Implement `status_donut_chart()` function
- [x] Implement `context_bar_chart()` function
- [x] Add dropdown options
- [ ] Test

---

## Phase 7: Implement Analysis Charts

### 7.1 Session Histogram

**File:** `charts/analysis.js`

**Function:** `session_histogram(data, ctx)`

**Features:**
- X-axis: duration buckets (0-15min, 15-30min, 30-60min, 1-2hr, 2-4hr, 4hr+)
- Y-axis: count of sessions
- Bar chart with categorical x-axis
- Shows session length distribution pattern

**Implementation:**
- Bucket sessions by duration
- Count per bucket
- Render as bar chart

### 7.2 Radar Chart

**File:** `charts/analysis.js`

**Function:** `radar_chart(data, ctx)`

**Features:**
- Compare top N projects (e.g., top 5 by time)
- Axes: Total Time, Session Count, Avg Session Length, Days Active, Recency
- Normalize each axis 0-100
- Overlay multiple projects

**Data Calculation:**
```javascript
{
  totalTime: project.total_time,
  sessionCount: project.sessions.length,
  avgSessionLength: totalTime / sessionCount,
  daysActive: unique(sessions.map(s => s.date)).length,
  recency: daysSinceLastSession
}
```

### 7.3 Tag Bubble Chart

**File:** `charts/analysis.js`

**Function:** `tag_bubble_chart(data, ctx)`

**Features:**
- Bubble chart (scatter with variable point size)
- X-axis: number of projects with tag
- Y-axis: total time for tag
- Bubble size: average time per project
- Color: random or by tag.color field

**Chart.js Config:**
```javascript
{
  type: 'bubble',
  data: {
    datasets: [{
      data: tags.map(t => ({
        x: t.project_count,
        y: t.total_time,
        r: t.avg_time_per_project / scale
      }))
    }]
  }
}
```

### Tasks
- [x] Implement `session_histogram()` function
- [x] Implement `radar_chart()` function
- [x] Implement `tag_bubble_chart()` function
- [x] Add dropdown options
- [ ] Test with various data shapes

---

## Phase 8: Update UI

### charts.html Updates

#### New Dropdown Options
```html
<select id="chart_type" name="chart_type">
  <!-- Existing -->
  <option value="pie">Pie</option>
  <option value="bar">Bar</option>
  <option value="scatter">Scatter</option>
  <option value="line">Line</option>
  <option value="calendar">Calendar</option>
  <option value="wordcloud">Wordcloud</option>
  <option value="heatmap">Heatmap</option>

  <!-- New: Hierarchy -->
  <optgroup label="Hierarchy">
    <option value="treemap">Treemap</option>
  </optgroup>

  <!-- New: Trends -->
  <optgroup label="Trends">
    <option value="stacked_area">Stacked Area</option>
    <option value="cumulative">Cumulative</option>
  </optgroup>

  <!-- New: Summary -->
  <optgroup label="Summary">
    <option value="status">Status</option>
    <option value="context">Context</option>
  </optgroup>

  <!-- New: Analysis -->
  <optgroup label="Analysis">
    <option value="histogram">Session Histogram</option>
    <option value="radar">Radar</option>
    <option value="bubble">Tag Bubble</option>
  </optgroup>
</select>
```

#### New Hidden Inputs
```html
<input type="hidden" id="hierarchy_link" value="{% url 'api_hierarchy' %}">
<input type="hidden" id="context_tally_link" value="{% url 'api_tally_by_context' %}">
<input type="hidden" id="status_tally_link" value="{% url 'api_tally_by_status' %}">
<input type="hidden" id="tags_tally_link" value="{% url 'api_tally_by_tags' %}">
```

#### Script Loading
```html
<!-- Chart modules -->
<script src="{% static 'core/js/charts/core.js' %}?v={{ static_version.charts }}"></script>
<script src="{% static 'core/js/charts/basic.js' %}?v={{ static_version.charts }}"></script>
<script src="{% static 'core/js/charts/time.js' %}?v={{ static_version.charts }}"></script>
<script src="{% static 'core/js/charts/hierarchy.js' %}?v={{ static_version.charts }}"></script>
<script src="{% static 'core/js/charts/trends.js' %}?v={{ static_version.charts }}"></script>
<script src="{% static 'core/js/charts/analysis.js' %}?v={{ static_version.charts }}"></script>
<script src="{% static 'core/js/charts/wordcloud.js' %}?v={{ static_version.charts }}"></script>
```

### Tasks
- [x] Update dropdown with optgroups
- [x] Add hidden inputs for new API endpoints
- [x] Update script tags for modular loading
- [ ] Test UI interactions

---

## Phase 9: Testing & Polish

### Testing Checklist
- [ ] All existing charts still work after refactor
- [ ] Each new chart renders correctly with data
- [ ] Each new chart shows empty state when no data
- [ ] Date filtering works for all charts
- [ ] Project filtering works where applicable
- [ ] Context filtering works where applicable
- [ ] Tag filtering works where applicable
- [ ] Charts are responsive on mobile
- [ ] Tooltips display correctly
- [ ] Colors are consistent across related charts

### Edge Cases
- [ ] No sessions in date range
- [ ] Single project only
- [ ] No subprojects
- [ ] No tags
- [ ] Very long project/subproject names
- [ ] Large datasets (1000+ sessions)

### Tasks
- [ ] Manual testing of all charts
- [ ] Fix any rendering bugs
- [ ] Optimize performance if needed
- [x] Update `static/` copy for collectstatic

---

## Implementation Order

Recommended sequence to minimize dependencies:

1. **Phase 1**: File refactor (foundation for everything else)
2. **Phase 2**: Add external dependencies
3. **Phase 5**: Trend charts (reuse session data, similar to existing)
4. **Phase 6**: Summary charts (simple, new endpoints)
5. **Phase 3**: Backend API updates (needed for remaining charts)
6. **Phase 7**: Analysis charts
7. **Phase 4**: Hierarchy charts (most complex)
8. **Phase 8**: UI updates (can be done incrementally)
9. **Phase 9**: Testing & polish

---

## Estimated Scope

| Phase | Files Changed | New Lines (approx) |
|-------|---------------|-------------------|
| 1. Refactor | 8+ | ~100 (reorganization) |
| 2. Dependencies | 1 | ~5 |
| 3. Backend APIs | 2 | ~150 |
| 4. Hierarchy | 1 | ~200 |
| 5. Trends | 1 | ~150 |
| 6. Summary | 1 | ~100 |
| 7. Analysis | 1 | ~250 |
| 8. UI | 1 | ~50 |
| 9. Testing | 0 | 0 |

**Total:** ~1000 new lines of code across ~15 files

---

## Notes

- Radar chart requires careful normalization to be meaningful
- Tag bubble chart depends on users actually using tags
- All new charts should follow existing patterns for consistency
