# UI Redesign — "Focus Desk"

Branch: `ui-redesign`. Reference mockup: `design_concepts_v2/focus-desk/`
(open `design_concepts_v2/index.html` for the full concept comparison).

**To resume: read this file, find the first chunk not marked DONE, do it.**

---

## The design

Focus Card's calm mobile system made desktop-native. Chosen by Henry
2026-07-26 from six concepts.

- **Surfaces** — soft translucent dark slabs, big radii (18–30px), real
  physical depth. Never frosted glass, terminal panes, paper or kanban
  (all rejected in round 1).
- **Type** — large and calm. Body 17px. Mono confined to numerals only.
- **Desktop layout** — a full-width HERO ZONE (focus deck + day timeline,
  both wide objects) above a two-track DESK: wide primary track
  (sessions — what you act on) beside a narrow ambient track
  (commitments + activity — what you glance at).
- **Nav** — no sidebar at any width. One pill: fixed bottom on phones,
  sticky floating top pill at ≥1000px. Overflow items in a bottom sheet.
- **Mobile** — the phone layout is the original Focus Card design,
  untouched. Desktop is an added layer, not a replacement.

### Non-negotiables (carried from the current app)

1. **Semantic colour convention is load-bearing.** Project names RED,
   subproject names BLUE, durations/totals GREEN, clock times CYAN,
   session notes YELLOW, brand ORANGE.
2. **User backdrop image** — full-bleed photo behind the workspace with an
   adjustable dim overlay (`--background-dim-opacity`), supporting upload /
   Bing daily / NASA APOD. Slabs stay translucent so it reads through.
3. **Dark-first.**

---

## Migration strategy

Two shells coexist during the port so **every commit leaves the app fully
working**:

- `core/templates/core/base.html` — legacy shell, loads `style.css`.
  Un-ported pages keep extending this and are unaffected.
- `core/templates/core/base_fd.html` — new shell, loads `focus_desk.css`
  only. Ported pages extend this.

Porting a page = switch its `{% extends %}` and rewrite its content block.
No page ever loads both stylesheets, so the two systems cannot collide
even though they share class names (`.btn`, `.stat`, `.text-red`, …).

Final chunk deletes the legacy shell and `style.css`, then renames
`base_fd.html` → `base.html`.

**Do not** try to merge the two stylesheets. **Do not** namespace the new
one under a wrapper class. The extends-switch is the whole mechanism.

---

## Chunks

Status: `TODO` / `WIP` / `DONE`

| # | Chunk | Templates | Status |
|---|-------|-----------|--------|
| 1 | Foundation: `focus_desk.css` + `base_fd.html` shell | — | **DONE** |
| 2a | Timeline backend (`core/timeline.py` + 21 tests) | — | **DONE** |
| 2b | Dashboard page port | `dashboard.html`, `partials/active_timers_dashboard.html` | TODO |
| 3 | Sessions | `list_sessions`, `update_session`, `delete_session` | TODO |
| 4 | Projects | `projects_list`, `create_project`, `update_project`, `delete_project`, `merge_projects` | TODO |
| 5 | Subprojects | `create_subproject`, `update_subproject`, `delete_subproject`, `merge_subprojects` | TODO |
| 6 | Timers | `timers`, `start_timer`, `stop_timer`, `remove_timer`, `partials/active_timers_home`, `partials/active_timers_timers`, `partials/timer_suggestion_card` | TODO |
| 7 | Commitments | `create_commitment`, `update_commitment`, `delete_commitment`, `partials/commitments_panel` | TODO |
| 8 | Contexts & Tags | `contexts`, `update_context`, `delete_context`, `tags`, `update_tag`, `delete_tag` | TODO |
| 9 | Charts | `charts` | TODO |
| 10 | Import / Export / Home | `import`, `export`, `home` | TODO |
| 11 | Users | `users/base`, `login`, `logout`, `register`, `password_reset`, `profile` | TODO |
| 12 | Insights | `llm_insights/insights` | TODO |
| 13 | Cutover: delete legacy shell + `style.css`, rename `base_fd` → `base` | — | TODO |

### Chunk 13 cutover checklist (add to as you go)

- Delete `core/templates/core/base.html`, rename `base_fd.html` → `base.html`,
  drop the `{% extends %}` churn.
- Delete `core/static/core/css/style.css` and `colours.css` once nothing
  references them (`grep -rn "style.css\|colours.css" core users llm_insights`).
- Split `core/static/core/js/script.js`: the `[data-utc-time]` conversion is
  still needed, the burger-menu half is dead once the legacy shell goes.
- Re-check whether jQuery is still required. Several page scripts use it
  (`dynamic_timers`, `search_projects`, `timer_search_projects`,
  `session_sliders`, `charts/*`), so it likely stays — confirm rather than
  assume.
- `core/templates/core/home.html` appears unused: `/` routes to
  `DashboardView` → `dashboard.html`. Confirm and delete if dead.

44 templates total.

---

## Per-chunk checklist

1. Port the templates — this is **design work, not mechanical translation**.
   Each page needs its own layout thinking within the system; the mockup
   only covers Dashboard.
2. Reuse existing classes from `focus_desk.css`. If a page genuinely needs
   a new component, **append it to `focus_desk.css`** in the same style —
   never inline styles, never a second stylesheet.
3. Run the suite: `./.venv/Scripts/python.exe manage.py test core users llm_insights`
   (check the runner's own exit code and the OK/FAILED line — piping to
   `tail` hides failures).
4. Verify in the browser at 1440 **and** 390 wide. Check no horizontal
   overflow (`document.documentElement.scrollWidth <= innerWidth`).
5. Update this file's status table.
6. Commit with the chunk number in the subject.

## Next up (chunk 2b) — how the dashboard should be assembled

`build_day_timeline(user, day=None)` in `core/timeline.py` returns everything
the chart needs, already as percentages:

```
{date, window_start_hour, window_end_hour,
 hours: [{hour, label, x_pct}],
 lanes: [{project, colour, total_minutes, live_minutes,
          blocks: [{session, is_live, minutes, start_pct, width_pct,
                    label, start_local, end_local}]}],
 gaps:  [{minutes, start_pct, width_pct}],
 now_pct, now_label}
```

`DashboardView.get_context_data` needs `context["timeline"] =
build_day_timeline(user)`. Everything else it already supplies.

Page structure, per the mockup (`design_concepts_v2/focus-desk/dashboard.html`):

1. `.desk-head` — eyebrow + title on the left, `.stat-strip` on the right.
2. **Hero, full width** — `.focus-deck` (one `.focus-card` per running timer,
   plus a `.focus-card--start`), then the timeline slab.
3. `.desk` — `.desk-main` holds recent sessions; `.desk-side` holds
   commitments then activity.

CSS classes for the timeline already exist in `focus_desk.css`
(`.fd-tl-slab`, `.fd-tl-lane`, `.fd-tl-block`, `.fd-tl-now`, …). Lane colour
comes from the data: `style="--proj: {{ lane.colour }}"`.

## Gotchas found so far

- Heavy inline `style=` attributes are all over the current templates
  (`dashboard.html` especially). Strip them; they are the thing that made
  the old UI hard to restyle.
- `list_sessions` / dashboard session rows rely on hover-slider marquees
  for long notes and project names. Replace with a real note column
  (desktop) or clamp-and-tap-to-expand (mobile) — never a marquee.
- The old `.card`-inside-`.card` nesting has no equivalent here. Slabs are
  containers, bands are rows; a band never nests in a band.
- `scripts/seed_finrod.py` seeds realistic data — useful for eyeballing
  pages with real content.
