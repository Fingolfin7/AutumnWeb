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
| 2b | Dashboard page port | `dashboard.html`, `partials/active_timers_dashboard.html` | **DONE** |
| 3 | Sessions | `list_sessions`, `update_session`, `delete_session` | **DONE** |
| 4 | Projects | `projects_list`, `create_project`, `update_project`, `delete_project`, `merge_projects` | **DONE** |
| 5 | Subprojects | `create_subproject`, `update_subproject`, `delete_subproject`, `merge_subprojects` | **DONE** |
| 6 | Timers | `timers`, `start_timer`, `stop_timer`, `remove_timer`, `partials/active_timers_timers`, `partials/timer_suggestion_card` | **DONE** (see note: `active_timers_home` left for chunk 13) |
| 7 | Commitments | `create_commitment`, `update_commitment`, `delete_commitment`, `partials/commitments_panel` | TODO |
| 8 | Contexts & Tags | `contexts`, `update_context`, `delete_context`, `tags`, `update_tag`, `delete_tag` | TODO |
| 9 | Charts | `charts` | **DONE** |
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
- `dynamic_timers.js` is now only used for its five-second fragment poll; its
  `updateDurations()` half targets legacy `.timer-duration` markup and matches
  nothing on the ported dashboard. Once chunks 6 and 10 land, split the poll
  out and drop the rest (it is also the last jQuery dependency on this page).
- The dashboard's `.fd-tl-slab` opts out of `.slab`'s `overflow: hidden` so
  timeline tooltips can escape upward. If another page needs the same, make it
  a modifier rather than changing `.slab`.
- `session_sliders.js` is no longer loaded by any ported page (notes clamp and
  expand instead of sliding). Delete it once chunks 6 and 10 stop referencing
  it, along with the `.session-note-slider` / `.project-name-slider` markup.

## Chunk 12 (Insights) — read this before starting

Not a shell swap. `llm_insights/insights.html` is ~270 lines of markup plus
~210 of inline script, and it loads its own `core/css/chat_style.css`, which
reads **fourteen variables that only exist in `style.css`/`colours.css`**:

```
--border-dark --dark-text --accent-color --main-red --light-text
--dark-background --card-bg-dark-alpha --card-background-dark --border-light
--main-muted --color-text-light --color-dodgerblue --color-blue-grey
--card-background-light
```

None are defined in `focus_desk.css`, so switching the extends alone gives a
chat UI with no colours. Two ways out, and they are not equal:

1. **Bridge the variables** — define those fourteen names in `focus_desk.css`
   in terms of Focus Desk tokens. Cheap and reversible, but the chat then
   keeps the old system's square corners and spacing inside the new shell, so
   it reads as a foreign page.
2. **Port `chat_style.css`** (594 lines) into the system properly — message
   bubbles become slabs/bands, the composer becomes `.fields`.

Prefer 2. Use 1 only as an explicitly temporary step, recorded here, and only
if the page must ship before there is time for 2.

Either way the inline `<script>` block should move to a real static file
first; it is the only page still carrying that much script inline, and it is
impossible to review inside a template.

## Chunk 3 notes (Sessions)

- **Row layout is a property of the LIST, not the page.** The `.desk .session`
  rules from chunk 1 became `.session-list .session`, and both the dashboard's
  recent-sessions slab and the Sessions page opt in with that class. Any future
  page showing session rows does the same.
- **Filters live in a sheet, per the nav model.** One search field plus a
  `.filter-launcher`; the sheet's controls are part of the same GET form, so
  Apply is an ordinary submit. Because the controls are hidden, the page echoes
  them back as `.filter-pill`s with a result count — otherwise a narrowed list
  that returns nothing is indistinguishable from a broken one. The old
  "Found N results" flash is gone; it also cost a second full run of the
  unpaginated query on every search.
- **`.fields` styles Django widgets by element.** `core/forms.py` sets widget
  attrs shared with pages still on the legacy shell, so classes cannot be added
  there without restyling un-ported pages. Wrap the form in `.fields` instead.
  Use this for every remaining form chunk.
- **Third-party markup is restyled, never renamed.** `allocation_editor.js`
  (`.attr-*`), `session_note_editor.js` and jQuery UI's autocomplete all build
  their own subtrees; focus_desk.css now has a Focus Desk dialect for each,
  under its own heading. Do not rename their classes.

## Chunk 4 notes (Projects)

- **`summarise_search_filters` now lives in `core/utils.py`** and is shared by
  the Sessions and Projects lists. Reuse it for any future filtered list rather
  than growing a second copy.
- **Shared partials cannot change design system alone.**
  `partials/commitments_panel.html` is included by update_project (4),
  update_subproject (5), update_context and update_tag (8). Its markup is
  untouched; focus_desk.css restyles its existing class names under
  "COMMITMENTS PANEL — compatibility dialect". **Chunk 7 rewrites the partial
  in native components and deletes that block** — do not let the compat rules
  outlive it.
- **Collapsed-by-default is markup, not script.** The legacy page collapsed
  Paused/Complete/Archived with jQuery after load, which flashed them open
  first. `.disclose.is-closed` is now rendered server-side.
- **`create_project` is routed at `path("create_subproject/")`** in
  `core/urls.py` — an existing naming mix-up, harmless but confusing. Worth
  fixing in chunk 13 along with the other cleanups.

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

## How the dashboard was assembled (chunk 2b, reference for later chunks)

`build_day_timeline(user, day=None)` in `core/timeline.py` returns everything
the chart needs, already as percentages and already labelled:

```
{date, window_start_hour, window_end_hour,
 hours: [{hour, label, x_pct}],
 lanes: [{project, colour, total_minutes, live_minutes,
          total_label, live_label,          # None when the figure is zero
          blocks: [{session, is_live, minutes, duration_label,
                    start_pct, width_pct, label, start_local, end_local}]}],
 gaps:  [{minutes, label, start_pct, width_pct}],
 now_pct, now_label}
```

Geometry reaches CSS through custom properties (`--x`, `--start`, `--w`,
`--proj`) set from those percentages. That is the ONE sanctioned use of a
`style=` attribute in this design system — data, never styling. The whole
timeline is wrapped in `{% localize off %}`: a locale that renders `20,007`
instead of `20.007` would silently break every position.

Things worth copying into the remaining chunks:

- **Polled fragments and `display: contents`.** `partials/active_timers_dashboard.html`
  is swapped in wholesale every five seconds by `dynamic_timers.js` and is
  rendered WITHOUT context processors, so it may only use its `timers` arg.
  Its wrapper is `.focus-cards { display: contents }`, which lets it carry the
  polling data-attributes while its cards stay layout children of
  `.focus-track` — that is how the "start something" card, which needs page
  context, sits beside them.
- **Server renders the first frame.** The hero timer's opening value comes from
  the `hero_duration` filter; `dashboard_desk.js` repaints the identical shape
  every second. `core/test_dashboard_desk.py` pins the format so the two
  cannot drift into a visible jump on the first tick.
- **Page JS goes in its own file.** `dashboard_desk.js` owns live cards, deck
  dots and the activity range; `focus_desk.js` stays shell-only.
- **Empty states are content.** `.empty` / `.fd-tl-empty` say what is missing
  and link to the action that fills it. The timeline still draws its axis on a
  blank day — an empty chart reads as "nothing yet", a missing one reads as
  "broken".

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
