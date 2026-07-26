# AutumnWeb UI Redesign — Content Inventory Brief

Audience: mockup designers who will **not** read the codebase.
Scope: three pages — **Dashboard (Home)**, **Projects List**, **Session Logs**.

Everything below is what the pages render *today*. Field/context names in `code font` are
the real Django template variables so you can trace anything back.

Terminology used throughout:

- **Project** — top-level tracked thing (`Projects`).
- **SubProject** — child task of exactly one project (`SubProjects`). A session can reference several.
- **Session** — one time record (`Sessions`): `start_time`, `end_time`, `note`, one project, N subprojects.
- **Context** — hard scope (Work / Personal / Study / General). A project has exactly 0-1.
- **Tag** — soft label, many-to-many with projects, optional hex `color`.
- **Commitment** — a recurring goal (X minutes or X sessions per period) attached to a project,
  subproject, context, or tag, with optional "time banking" (carry surplus forward).
- **Durations are always minutes (float)** in the data; templates format them.

---

## 0. Shared chrome (present on all three pages, from `core/templates/core/base.html`)

Not part of the three-page brief per se, but every mockup sits inside it.

| Element | Content |
|---|---|
| Top ribbon, left | Autumn leaf logo + wordmark "Autumn", links to Home |
| Top ribbon, right | Burger icon (mobile), `{{ user.username }}`, circular profile picture → `/profile/` |
| Left nav (`nav.left-panel`) | Home, Manage Projects, Timers, Session Logs, Insights (only if `user.profile.ai_features_enabled`), Charts, Import, Export, Log out (POST form) |
| Messages strip | Django messages: green card (success), red card (error), blue card (info) |
| Body | `dark-mode` class always; optional full-page background photo (user upload, Bing daily, or NASA APOD) dimmed by `--background-dim-opacity` |

Page `<title>` comes from `title`: "Autumn", "Projects", "Sessions".

### Duration formatting filters (use these exact string shapes in mockups)

| Filter | Used for | Example output |
|---|---|---|
| `min_formatter` | project totals, live timer elapsed | `13 days 22 minutes`, `43 minutes 18 seconds` |
| `min_formatter_two` | dashboard Today / This Week tiles (max 2 units) | `5 hours 12 minutes`, `1 day 17 hours` |
| `duration_formatter` | per-session duration, per-day totals | `01h 36m`, `32m 45s`, `02d 04h 10m` |
| `time_formatter` | session start/end clock time | `09:12:04` |
| `date_formatter` | project start / last-updated | `14 January 2026` |
| `day_date_formatter` | session date group headings | `Saturday 25 Jul 2026` |

---

# PAGE 1 — Dashboard / Home

Template `core/templates/core/dashboard.html`, view `core/views/dashboard.py::DashboardView`.
URL: `/` (name `home`).

## 1.1 Information displayed

### A. Quick-stats row — 4 cards, CSS grid `repeat(auto-fit, minmax(200px,1fr))`

| Card label | Context var | Notes |
|---|---|---|
| **Today** | `today_total` → `min_formatter_two` | green. Sum of `duration` of sessions whose `end_time` ≥ local midnight. Running timers excluded. |
| **This Week** | `week_total` → `min_formatter_two` | cyan. Week starts **Monday** local. |
| **Active Timers** | `active_timers_count` | yellow if > 0, muted grey if 0. Bare integer. |
| **Current Streak** | `daily_streak.current_streak` | red. Rendered as `N day` / `N days`. |

### B. Active Timers panel — `core/templates/core/partials/active_timers_dashboard.html`

Whole `<section>` is `display:none` when there are no timers. Left border 4px yellow.
Collapsible header: play-circle icon + "Active Timers" + chevron toggle.
Auto-refreshes via `data-refresh-url` (`active_timers_fragment`); shows max 5 (`data-max-visible="5"`).

Per timer row (`timer` = a `Sessions` row with `end_time IS NULL`):

- `timer.project.name` — red, bold
- `timer.subprojects.all` — rendered literally as `[ 'auth', 'billing' ]`, names blue
- `timer.duration|min_formatter` — green, **monospace**, ticking client-side every second
- If `timer.auto_stop_at`: `stops in <countdown>` — a live countdown
- Actions (icon buttons, right-aligned): **Restart** (redo icon), **Stop** (stopwatch icon), **Remove** (trash icon)

### C. Two-column area (flex, wraps at 300px min-width)

#### C1. Commitments (left column) — `commitments_data`, sorted **most-behind first** (`progress.percentage` ascending)

Collapsible section header: bullseye icon (cyan) + "Commitments".
One card per commitment (dark translucent card). Per card:

- **Target name** `item.commitment.target_name`, bold, 1.1em, colour depends on `aggregation_type`:
  project → red, subproject → blue, context → orange, tag → the tag's own `color`.
  Links to the target's edit page (`update_project` / `update_subproject` / `update_context` / `update_tag`).
- Small muted `(Project)` / `(Subproject)` / `(Context)` / `(Tag)` — `get_aggregation_type_display`
- Right-aligned muted period word: `item.progress.period` → one of `daily weekly fortnightly monthly quarterly yearly`
- Row: label "Progress" (accent) + `actual / target` (green). `m` suffix appended when `commitment_type == 'time'`; no suffix for session counts.
- **Progress bar** — width = `progress.percentage`; bar gets a status class driving its colour:
  `complete` (≥100%), `approaching` (≥75), `on-track` (≥50), `warning` (≥25), `behind` (<25)
- **Banking row** (only if `commitment.banking_enabled`), two halves:
  - `Bank (reconciled): +145m` — green when ≥ 0, red when negative
  - `This period (unbanked): -132m` — same colour rule
- **Streak row**:
  - flame icon (red if `streak.current_streak > 0`, else muted) + `N period` / `N periods`
  - a row of up-to-8 tiny 1.2rem squares, oldest → newest, one per past period:
    - **current period** → yellow bg, hourglass icon
    - **met** → green bg, check icon
    - **met but rescued by bank** (`saved_by_bank`) → cyan bg, check icon
    - **missed** → red bg, times icon
    - each square's tooltip: `actual/target`, plus `(bank covered deficit)` when rescued
- Empty state: card with "No active commitments. **Add one**." linking to `create_commitment_generic`.

#### C2. Activity (right column) — `daily_streak.recent_days` (30 days precomputed)

Collapsible header: calendar icon (green) + "Activity". Inside a single card:

- Range buttons: **Week** (7) / **2 weeks** (14, active by default) / **Month** (30) — JS-only, no page load
- Weekday header row: Mon Tue Wed Thu Fri Sat Sun
- Calendar grid of day cells, oldest → newest, each showing the **day-of-month number**;
  cell class `is-active` (had ≥1 completed session) or `is-inactive`. Tooltip = `Jul 24`.
  First visible cell is offset into its correct weekday column.
- Caption: `Last 14 days activity` (updates with the range buttons)

### D. Recent Sessions — `grouped_sessions`

Collapsible header: history icon (blue) + "Recent Sessions".
**Only the 3 most recently ended sessions** (`Sessions.order_by('-end_time')[:3]`), then grouped by
local end date into `OrderedDict{ 'MM-DD-YYYY': {sessions, total_duration} }`.

Per date group: `<h3>` underlined `Saturday 25 Jul 2026` + green `(05h 12m)` — note the group total is
the total of *the listed sessions only*, so on the dashboard it is **not** the real day total.

Per session card, all on **one horizontal `.session-row`**:

`start_time` (cyan) · "to" · `end_time` (cyan) · `duration` (`01h 36m`) · optional yellow `DST` badge
(when `session.crosses_dst_transition`) · `project.name` (red, links to `update_project`) ·
subprojects rendered as `[ 'auth', 'billing' ]` (blue, each links to `update_subproject`) ·
`->` if there's a note · `note` rendered **as markdown HTML**, yellow · then actions:

- Pen icon → `update_session`
- Trash icon → `delete_session`
- **Restart** (redo icon) — a POST form to `start_timer` carrying hidden `project` + one hidden
  `subprojects` input per subproject. *(This restart button exists on the dashboard only, not on Session Logs.)*

Project name and note are inside "slider" spans (`session_sliders.js`) — long text marquees/scrolls on hover
because the row does not wrap.

Footer link: **View all sessions →** to `sessions`.
Empty state: "No sessions yet. **Start a timer** to begin tracking."

## 1.2 Actions on the Dashboard

| Control | Destination / effect |
|---|---|
| 3 collapse chevrons | collapse Commitments / Activity / Recent Sessions (client only) |
| Timer Restart / Stop / Remove | `restart_timer/<id>`, `stop_timer/<id>`, `remove_timer/<id>` (plain GET links) |
| Commitment target name | edit page for the project/subproject/context/tag |
| "Add one" (empty commitments) | `create_commitment_generic` |
| Activity Week / 2 weeks / Month | client-side range change |
| Session pen / trash | `update_session/<id>`, `delete_session/<id>` |
| Session redo | POST `start_timer` — restarts that project+subprojects combo |
| Project name / subproject names | `update_project/<id>`, `update_subproject/<id>` |
| "View all sessions →" | Session Logs page |

**There is no "start a new timer" control on the dashboard** unless the sessions list is empty — a notable gap.

---

# PAGE 2 — Projects List

Template `core/templates/core/projects_list.html`, view `core/views/projects.py::ProjectsListView`.
URL: `/projects/` (name `projects`). No pagination — **every** project is rendered.

## 2.1 Filter bar (a single `.card.flex-row` GET form, `#search_form`)

Seven controls in one wrapping row:

1. **Search** — text input, id `project-search`, placeholder "Projects", **AJAX autocomplete** against
   the projects API; matches drop into `#project-search-results`
2. **Start Date** — native `<input type=date>`
3. **End Date** — native `<input type=date>`
4. **Context** — `<select>`, first option "All Contexts", then one per user context
5. **Tags** — `<details>` disclosure, summary reads "Select tags", body is a checkbox list of every tag
6. **Exclude Projects** — `<details>` disclosure, summary "Select projects to exclude", body has its own
   inline "Search projects..." text filter plus a checkbox per project. Options auto-hide based on the
   active context/tag selection (`EXCLUDE_PROJECT_META` JSON blob).
7. **Search** submit button (magnifier icon)

Below the form, four standalone buttons:

| Button | Style | Goes to |
|---|---|---|
| **+ Create Project** | primary | `create_project` |
| **Merge Projects** (code-branch icon) | secondary | `merge_projects` |
| **Manage Contexts** (layer-group icon) | secondary | `contexts` |
| **Manage Tags** (tags icon) | secondary | `tags` |

## 2.2 Project groups — `grouped_projects`

Four groups, always in this order, each rendered only if non-empty:
**Active**, **Paused**, **Complete**, **Archived** (from `status_choices`).

Group heading is a clickable `<h2>`: underlined status name + small `(count)` + caret icon.
**Paused, Complete and Archived are collapsed on page load** (jQuery `.toggle('slow')`); Active is open.

Cards inside `div.grid-rows`. Each project card is a 4-row `<table>` (yes, a table):

| Row | Content | Colour |
|---|---|---|
| 1 | `<h3>` `project.name`, links to `update_project/<id>` | red |
| 2 | *(only if the project has tags)* tags icon + comma-separated tag names, each linking to `update_tag/<id>`, each rendered in its own `tag.color` | per-tag |
| 3 | `project.total_time \| min_formatter` (derived from sessions, e.g. `13 days 22 minutes`) | green |
| 4 | `project.start_date` `->` `project.last_updated`, both `date_formatter` | cyan |

Sort order inside a group: most recently updated first (`-derived_last_updated`).

Empty state (no projects at all, `has_projects` false): a full-width "such empty" meme image.

**Data the view computes but the template never shows (redesign opportunity):**
`commitment_progress` — a `{project_id: progress dict}` map with `actual`, `target`, `percentage`,
`status`, `balance` for every project that has an active commitment. Also **not** shown anywhere on
this page: the project's **context**, its **description**, its **subprojects**, and its **session count**.

## 2.3 Actions

| Control | Destination |
|---|---|
| Filter form submit | reloads `/projects/?project_name=…&start_date=…&end_date=…&context=…&tags=…&exclude_projects=…` |
| Create Project | `create_project` |
| Merge Projects | `merge_projects` |
| Manage Contexts | `contexts` |
| Manage Tags | `tags` |
| Status heading | collapse/expand that group (client only) |
| Project name | `update_project/<id>` (edit page: rename, status, context, tags, subprojects, commitments) |
| Tag name | `update_tag/<id>` |

No per-card actions at all today — no start-timer, no edit, no delete on the card.

---

# PAGE 3 — Session Logs

Template `core/templates/core/list_sessions.html`, view `core/views/sessions.py::SessionsListView`.
URL: `/sessions/` (name `sessions`). **Paginated: `paginate_by = 7`** — seven sessions per page.

## 3.1 Filter bar

Identical to the Projects filter bar **plus one more field**, and **without** the four management buttons:

1. Search (project autocomplete) 2. Start Date 3. End Date 4. Context 5. Tags 6. Exclude Projects
7. **Note** — text input `note_snippet`, placeholder "Note Snippet" (substring search inside session notes)
8. Search submit

When any of `project_name` / `start_date` / `end_date` / `note_snippet` is present, a green success message
appears above the content: **"Found 34 results"** (count is of the whole filtered queryset, not the page).

## 3.2 Session list

- Centred `<h2>` **Sessions** heading (only when there are results)
- Then the same date-group structure as the dashboard: `<h3>` underlined `Friday 24 Jul 2026` +
  green `(07h 30m)` group total. **Because grouping happens after pagination, a day can be split
  across two pages and its "total" is only the total of the rows on this page.**
- Session rows are byte-for-byte the same layout as the dashboard's, **minus the Restart button**:
  start (cyan) · to · end (cyan) · duration · optional `DST` badge · project (red, linked) ·
  `[ 'sub', 'sub' ]` (blue, linked) · `->` · markdown note (yellow) · pen + trash buttons.
- Empty state: the "such empty" meme image.

## 3.3 Pagination (bottom section, only when `is_paginated`)

Row of secondary buttons: `«` first, `‹` previous, then numeric buttons for
`current-1`, `current`, `current+1`, then `›` next, `»` last. All existing query params are preserved
via the `param_replace` tag. The current page number is **not visually distinguished** — every
number button has identical styling.

## 3.4 Actions

| Control | Destination |
|---|---|
| Filter submit | `/sessions/?project_name=…&start_date=…&end_date=…&note_snippet=…&context=…&tags=…&exclude_projects=…&page=…` |
| Project name | `update_project/<id>` |
| Subproject name | `update_subproject/<id>` |
| Pen | `update_session/<id>` — full edit: project, subprojects (+ % allocation), start, end, note |
| Trash | `delete_session/<id>` — confirmation page |
| Pagination buttons | same URL with `page=N` |

No bulk select, no export-this-view, no "add a session manually" control on this page.

---

# 4. SAMPLE DATA — use these EXACT values in every mockup

**Reference "now" for all mockups: Saturday 25 July 2026, 17:47 local.**
Week starts Monday 20 July 2026. Timezone: Europe/Prague. User: `finrod`.

## 4.1 Contexts

| id | name | description |
|---|---|---|
| 1 | Work | Client and employer time |
| 2 | Personal | Side projects and home |
| 3 | Study | Courses and reading |
| 4 | General | Default context |

## 4.2 Tags (name + colour — use the hex exactly)

| id | name | color |
|---|---|---|
| 1 | client | `#e0a458` |
| 2 | deep-work | `#38bdf8` |
| 3 | oss | `#4ade80` |
| 4 | maintenance | `#a78bfa` |
| 5 | writing | `#f472b6` |

## 4.3 Projects (7 — covers all four status groups)

| id | Project | Status | Context | Tags | Subprojects | total_time (min) | rendered `min_formatter` | start_date | last_updated |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **Atlas API** | Active | Work | client, deep-work | auth, billing, migrations, code-review | 18742 | `13 days 22 minutes` | 14 January 2026 | 25 July 2026 |
| 2 | **Autumn** | Active | Personal | oss, deep-work | ui-redesign, mcp-server, docs | 9468 | `6 days 13 hours 48 minutes` | 03 September 2025 | 25 July 2026 |
| 3 | **Rust by Example** | Active | Study | deep-work | ownership, async, exercises | 3215 | `2 days 5 hours 35 minutes` | 11 May 2026 | 25 July 2026 |
| 4 | **Newsletter** | Active | Personal | writing | drafting, editing | 1290 | `21 hours 30 minutes` | 02 March 2026 | 24 July 2026 |
| 5 | **Homelab** | Paused | Personal | maintenance | proxmox, backups, networking | 2455 | `1 day 16 hours 55 minutes` | 19 October 2025 | 23 July 2026 |
| 6 | **Portfolio Site** | Complete | Personal | oss, writing | design, deploy | 4120 | `2 days 20 hours 40 minutes` | 07 June 2025 | 28 February 2026 |
| 7 | **Thesis Notes** | Archived | Study | writing | lit-review, drafting | 11930 | `8 days 6 hours 50 minutes` | 21 September 2024 | 12 December 2025 |

Projects-page group counts: **Active (4)**, **Paused (1)**, **Complete (1)**, **Archived (1)**.

## 4.4 Sessions (15 — Session Logs page 1 shows the first 7)

Durations shown as they render with `duration_formatter`.

### Saturday 25 Jul 2026 — group total `05h 12m` (312 min)

| # | Start | End | Duration | Project | Subprojects | Note |
|---|---|---|---|---|---|---|
| 1 | 15:20:00 | 16:55:30 | `01h 35m` | Atlas API | `['billing', 'migrations']` | Stripe webhook backfill; wrote the idempotency-key migration |
| 2 | 13:40:00 | 14:12:45 | `32m 45s` | Rust by Example | `['async']` | Pinning chapter — re-read it twice |
| 3 | 11:05:00 | 12:32:18 | `01h 27m` | Autumn | `['ui-redesign']` | **Sketching** the new session card — 3 columns feels cramped on mobile |
| 4 | 09:12:04 | 10:48:31 | `01h 36m` | Atlas API | `['auth']` | Rate-limiter tests green; token refresh still flaky under load |

### Friday 24 Jul 2026 — group total `07h 30m` (450 min)

| # | Start | End | Duration | Project | Subprojects | Note |
|---|---|---|---|---|---|---|
| 5 | 20:10:00 | 21:38:00 | `01h 28m` | Autumn | `['ui-redesign', 'docs']` | Dark-mode contrast pass. See [issue #41](#) |
| 6 | 16:00:00 | 17:22:00 | `01h 22m` | Rust by Example | `['ownership', 'exercises']` | Borrow checker finally clicked on ex. 12 |
| 7 | 13:30:00 | 15:05:00 | `01h 35m` | Atlas API | `['code-review']` | *(no note)* |
| 8 | 12:15:00 | 12:50:00 | `35m 00s` | Newsletter | `['drafting']` | Issue #14 outline: "why your time tracker lies to you" |
| 9 | 09:45:00 | 11:30:00 | `01h 45m` | Atlas API | `['auth']` | Pairing with Dana on the OAuth device flow |
| 10 | 08:35:00 | 09:20:00 | `45m 00s` | Autumn | `['mcp-server']` | Added the `tally_by_tags` tool; docstrings still thin |

### Thursday 23 Jul 2026 — group total `06h 05m` (365 min)

| # | Start | End | Duration | Project | Subprojects | Note |
|---|---|---|---|---|---|---|
| 11 | 19:30:00 | 20:56:00 | `01h 26m` | Rust by Example | `['async']` | *(no note)* |
| 12 | 14:00:00 | 15:12:00 | `01h 12m` | Newsletter | `['editing']` | Cut 400 words. Still too long. |
| 13 | 11:15:00 | 12:47:00 | `01h 32m` | Autumn | `['mcp-server']` | Session allocation editor — basis points everywhere |
| 14 | 10:20:00 | 11:00:00 | `40m 00s` | Homelab | `['backups']` | restic prune took forever; 4 snapshots pruned |
| 15 | 08:50:00 | 10:05:00 | `01h 15m` | Atlas API | `['migrations']` | Zero-downtime column-drop rehearsal on staging |

**Which page shows what:**
- **Dashboard "Recent Sessions"** → sessions **#1, #2, #3 only**, under a single heading
  `Saturday 25 Jul 2026 (03h 34m)` — the group total is 214.45 min because only three sessions are listed.
  *(Deliberate quirk of the current code; keep it or fix it, but note it.)*
- **Session Logs page 1** → sessions **#1–#7**: heading `Saturday 25 Jul 2026 (05h 12m)` with 4 rows,
  then heading `Friday 24 Jul 2026 (04h 25m)` with 3 rows (#5, #6, #7 — the rest of Friday spills to page 2).
- **Session Logs pagination** → `is_paginated` true, **5 pages**, currently on page 1
  (33 sessions total in the filtered set).

Use session **#1** as the "long note" stress case and session **#5** as the
"markdown link inside a note" case.

## 4.5 Active timers (2 running right now)

| Project | Subprojects | started | elapsed (`min_formatter`) | auto_stop_at | countdown |
|---|---|---|---|---|---|
| Atlas API | `[ 'auth' ]` | 17:04:22 | `43 minutes 18 seconds` | 19:04:22 | `stops in 01:16:42` |
| Rust by Example | `[ 'exercises' ]` | 16:58:00 | `49 minutes 40 seconds` | — | *(no countdown shown)* |

## 4.6 Dashboard quick stats

| Tile | Value | Rendered |
|---|---|---|
| Today | `today_total` = 312 min | **5 hours 12 minutes** |
| This Week | `week_total` = 2486 min | **1 day 17 hours** |
| Active Timers | `active_timers_count` = 2 | **2** |
| Current Streak | `daily_streak.current_streak` = 23 | **23 days** |

## 4.7 Activity calendar (`daily_streak.recent_days`, 30 days: Fri 26 Jun → Sat 25 Jul 2026)

Active (filled) on **every day from 3 Jul through 25 Jul** (23 consecutive days — that's the streak),
plus 26 Jun, 27 Jun, 29 Jun, 30 Jun, 1 Jul.
Inactive (empty) on exactly: **28 Jun, 2 Jul**.
First cell (26 Jun) is a **Friday** → starts in grid column 5. Default visible range = last **14** days
(12 Jul → 25 Jul), all of which are active, so the default view is a solid block — design the
7 / 14 / 30 toggle so the sparser 30-day view is the interesting one.

## 4.8 Commitments (3, in dashboard display order — most behind first)

### 1. **Study** — Context, weekly, time-based *(orange target name)*

- Progress: **195m / 480m** → **40.6 %** → status `warning`
- Banking enabled: `Bank (reconciled): -60m` (red) · `This period (unbanked): -285m` (red)
- Streak: **0 periods** (flame icon muted)
- 8 period cells, oldest → newest:
  `met 512/480` · `missed 300/480` · `met 496/480` · `missed 210/480` · `met 520/480` ·
  `met 488/480` · `missed 344/480` · `current 195/480`

### 2. **Atlas API** — Project, weekly, time-based *(red target name)*

- Progress: **468m / 600m** → **78.0 %** → status `approaching`
- Banking enabled: `Bank (reconciled): +145m` (green) · `This period (unbanked): -132m` (red)
- Streak: **6 periods** (flame red)
- 8 period cells, oldest → newest:
  `missed 402/600` · `met 655/600` · `met 612/600` · `met 705/600` ·
  **`saved-by-bank 548/600`** (cyan cell) · `met 690/600` · `met 601/600` · `current 468/600`

### 3. **Autumn** — Project, weekly, **session-based** *(red target name)*

- Progress: **6 / 5** → **100 %** → status `complete`  *(note: no `m` suffix — it counts sessions)*
- Banking **disabled** → the whole bank row is absent from this card
- Streak: **11 periods** (flame red)
- 8 period cells, oldest → newest:
  `met 6/5` · `met 7/5` · `met 5/5` · `met 8/5` · `met 6/5` · `met 5/5` · `met 9/5` · `current 6/5`

These three cards exercise every visual state: warning bar, approaching bar, complete bar,
banked-positive, banked-negative, no-bank, zero streak, long streak, and a bank-rescued period.

## 4.9 Sample values for the projects-page hidden data (if a redesign surfaces it)

`commitment_progress` would map: project 1 (Atlas API) → 468/600, 78 %, `approaching`;
project 2 (Autumn) → 6/5, 100 %, `complete`. No other project has a commitment.
Session counts if you want them on cards: Atlas API 214, Autumn 168, Rust by Example 47,
Newsletter 23, Homelab 41, Portfolio Site 66, Thesis Notes 191.

---

# 5. Which page is heaviest / most cramped today

**Session Logs is the most cramped page, and by a wide margin.** The single `.session-row` packs
**nine** things onto one non-wrapping horizontal line — start time, "to", end time, duration, optional
DST badge, project name, a bracketed subproject list, an arrow, a full markdown note, and two icon
buttons. Long project names and long notes literally do not fit, which is why the codebase ships a
`session_sliders.js` marquee hack to scroll them on hover. On top of that the filter bar above it is
the widest on the site (**eight** controls in one wrapping flex row, two of which are `<details>`
dropdowns), and the pagination strip at the bottom shows up to seven buttons with **no active-page
highlight**. Only 7 rows fit per page, so a normal week takes 4–5 page loads to read.

**The Dashboard is the heaviest in terms of quantity of distinct information** — 4 stat tiles, a live
auto-refreshing timer panel, N commitment cards each with 5 sub-elements (name, period, progress
numbers, bar, bank row, streak strip), a 30-day activity heatmap with its own range switcher, and a
recent-sessions list that reuses the cramped session row — but it is laid out generously and its three
collapsible sections give it breathing room. Its real problems are (a) inline `style="…"` everywhere
rather than classes, (b) only **3** recent sessions, which is too few to be useful next to a 30-day
heatmap, (c) the misleading per-day total on that truncated list, and (d) no way to start a timer.

**Projects List is the lightest and the most under-used.** Each card is a 4-row `<table>` showing only
name, tags, total time, and a date range; three of the four status groups start collapsed, so a
typical page is one short row of cards over three collapsed headings. The view already computes
commitment progress per project and never renders it, and the card omits context, description,
subprojects, and session count entirely — the most headroom for a redesign.
