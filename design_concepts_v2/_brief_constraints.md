# Autumn — Design Constraints Brief (v2 mockup round)

Read this before drawing anything. It records (a) the palette in production, (b) what may
**not** change, (c) five concepts the owner already saw and rejected, and (d) the real
problems a new design is expected to solve.

Source of truth for everything below:
- `core/static/core/css/style.css` (2987 lines — `:root` block at L16–56, "Night Ledger" restyle layer from ~L2100 down)
- `core/static/core/css/colours.css` (legacy background-utility classes)
- `core/templates/core/base.html` (app shell)
- `core/templates/core/dashboard.html` (worst-offender page)

---

## 1. Current "Night Ledger" token palette

### Brand / chrome
| Token | Hex | Used for |
| --- | --- | --- |
| `--primary-color` | `#101214` | Near-black base; same value as `--dark-background`. Used by `.text-primary`. |
| `--accent-color` | `#c98245` | **The brand orange.** Fill for `.primary-button` / `.timer-button`, `.bordered-top` top rule, `<u>` underline colour on date headers, focus states. |
| `--accent-hover` | `#d59657` | Lighter orange on button hover. |
| `--brand-orange` | `#c98245` | Alias of accent; drives `.text-orange` and `.main-link:hover`. |
| `--secondary-accent-color` | `#4e9a8e` | Teal fill for `.secondary-button`. |
| `--ribbon-bg` | `#0a0c0e` | Top ribbon background (darker than the page — the ribbon reads as a lid). |
| `--ribbon-text` | `#d9dedb` | Ribbon foreground. |
| PWA `theme-color` | `#8f3f24` | Hard-coded in `base.html` meta tag — deeper burnt orange. |

### Backgrounds & borders
| Token | Value | Used for |
| --- | --- | --- |
| `--dark-background` | `#101214` | `body.dark-mode` background; also the *text* colour on orange/teal buttons. |
| `--light-background` | `#f4f1ec` | `body.light-mode` background (secondary mode, see §2.3). |
| `--card-background-dark` | `#171a1d` | Nominal dark card colour. |
| `--card-bg-dark-alpha` | `rgba(23,26,29,0.9)` | **Actual** dark card fill — 90 % opaque so a backdrop image reads through faintly. |
| `--card-background-light` | `#fffdf8` | Light-mode card. |
| `--border-dark` | `#2b3135` | Every hairline in dark mode: card border, ribbon bottom rule, `.section-header` underline, sidebar right rule, `.collapse-toggle` border. |
| `--border-light` | `#d7d0c4` | Light-mode equivalent. |
| `--section-border-width` | `1px` | Ribbon border width. |
| `--img-mix-background` | `rgba(8,10,12, var(--background-dim-opacity, 0.55))` | The dim scrim over the user backdrop. |
| `--surface-1` | `#171a1d` | Sidebar hover fill, mobile sidebar fill. |
| `--surface-2` | `#1d2225` | Raised sub-surfaces. |
| `--surface-3` | `#121518` | Recessed surfaces (allocation editor rows). |
| `--line-soft` | `rgba(217,222,219,0.09)` | Faint list separators, avatar ring. |
| `--focus-ring` | `rgba(201,130,69,0.24)` | Orange focus glow. |
| `--shadow-soft` | `0 0.9rem 2rem rgba(0,0,0,0.28)` | Only shadow in the system; applied to dark cards. |
| `.left-panel` bg | `rgba(12,14,16,0.82)` (literal) | Sidebar — deliberately translucent so the backdrop image shows behind nav. |

### Text
| Token | Hex | Used for |
| --- | --- | --- |
| `--dark-text` | `#d9dedb` | Body text in dark mode (a cool off-white, not pure `#fff`). |
| `--light-text` | `#22201c` | Body text in light mode. |
| `--main-muted` | `#848d88` | Sage-grey. Section-header labels, sidebar links at rest, `h4`, secondary metadata. |

### Semantic colours (the load-bearing set — see §2.1)
| Token | Hex | Meaning in the UI |
| --- | --- | --- |
| `--main-red` | `#be675f` | **Project names.** Also negative balances, `.progress-bar.behind`, error cards. |
| `--main-blue` | `#7896b8` | **Subproject names.** Also the "Recent Sessions" section icon. |
| `--main-green` | `#7ca36a` | **Durations and totals.** Also positive balances, `.progress-bar.complete`. |
| `--main-cyan` | `#4e9a8e` | Clock times (session start/end stamps), info cards, `.secondary-button`. |
| `--main-yellow` | `#b9a66a` | Session notes, DST warnings, running-timer card tint (`rgba(185,166,106,0.09)`), `.progress-bar.on-track`. |
| `--main-magenta` | `#9b83a7` | Reserved / rarely used. |

Two literal hexes bypass the token set inside `.progress-bar`: `#f97316` (`.warning`) and
`#84cc16` (`.approaching`). Both should become tokens in v2.

### Legacy `colours.css`
A second `:root` block defines `--color-dark-red #be675f`, `--color-cobalt-blue #7896b8`,
`--color-kellygreen #7ca36a`, `--color-ferngreen`/`--color-lincolngreen #4e9a8e`,
`--color-forestgreen #607f58`, `--color-blue-grey #4c5b64`, `--color-text-light #d9dedb`,
`--color-transparent-white rgba(255,255,255,0.2)`. These feed background-colour utility
classes (`.cadmium-red`, `.cobalt-blue`, `.lincolngreen`) used only for Django message
banners in `base.html`. They duplicate the semantic set — v2 should collapse the two files
into one token layer, but the *hexes* must survive.

### Type
- UI: `"Aptos", "Segoe UI", "Helvetica Neue", Arial, sans-serif`
- Numeric / mono (durations, timers, stat values, device codes): `"Cascadia Mono", "SFMono-Regular", Consolas, "Liberation Mono", monospace`
- Headings `h1–h4`: `font-weight: 650`, `line-height: 1.2`, `letter-spacing: 0`
- `h4` and `.section-header`: `0.82rem`, uppercase, `letter-spacing: 0.08em`, muted colour
- Corners are **square**: `border-radius: 0` is applied to `.card` and every button class. Progress bars are the only rounded element (`8px` pill).

---

## 2. NON-NEGOTIABLES

### 2.1 The semantic text-colour convention
This is the single most load-bearing rule in the app. It is inherited from the Autumn CLI
and the owner reads the UI by colour, not by label:

- **Project names → red `#be675f`** (`.text-red`)
- **Subproject names → blue `#7896b8`** (`.text-blue`)
- **Durations / totals → green `#7ca36a`** (`.text-green`)
- **Clock times → cyan `#4e9a8e`** (`.text-cyan`)
- **Notes → yellow `#b9a66a`** (`.text-yellow`)
- **Brand / accent → orange `#c98245`** (`.text-orange`, buttons, brand marks)

A representative session row (`dashboard.html`) is literally:
`cyan 09:15  to  cyan 10:40   mono-green 1h 25m   red ProjectName   ['blue SubA', 'blue SubB'] -> yellow note`

Any new concept **must** carry these hues at roughly these values and these meanings.
You may retune saturation/lightness slightly for contrast, and you may change *where* the
colour lands (chip, rule, dot, left border) — but red-means-project / blue-means-subproject /
green-means-duration / orange-means-brand cannot be reassigned, dropped, or replaced by a
monochrome or single-hue scheme. Do not propose "one accent colour, everything else grey."

### 2.2 Full-bleed user backdrop with adjustable dim
`base.html` sets, on `<body>`, `--workspace-bg-image` (user upload, Bing daily, or NASA
APOD) and `--background-dim-opacity` (a per-user float from the profile). `style.css`
renders it as `body.bg-active::before` (fixed, `inset:0`, `cover`, `z-index:0`) plus
`body.bg-active::after` (fixed scrim, `rgba(8,10,12,var(--background-dim-opacity,0.55))`,
`z-index:1`), with `.container` lifted to `z-index:2`.

The design must therefore:
- Leave real estate where the image is visible — the app cannot be a wall of opaque panels edge to edge.
- Keep surfaces partly translucent (current: cards `rgba(23,26,29,0.9)`, sidebar `rgba(12,14,16,0.82)`).
- Stay legible across the **whole** dim range, from nearly-transparent to nearly-black. Do not design against one hand-picked photo.
- Note the tension: concept 2 was faulted precisely for killing this feature with opaque panes.

### 2.3 Dark-first
`<body class="dark-mode">` is hard-coded in the template for every user state including
logged-out. A `.light-mode` rule set exists and must keep working, but it is secondary —
design the dark surface first and derive light from it, never the reverse. Dark mode is not
an inverted variant of a light design.

### 2.4 Structural givens
- Django templates + jQuery + Font Awesome 5. No build step, no framework. Mockups must be reproducible in plain CSS.
- PWA-installed and used on phones — the layout must survive `max-width: 975px`, where a burger toggles the sidebar and the global font-size drops to 12px.
- The nav set is fixed: Home, Manage Projects, Timers, Session Logs, Insights (conditional), Charts, Import, Export, Log out.
- The dashboard must keep showing: quick stats, commitments with progress bars + per-period streak squares, an activity calendar, active timers, and date-grouped recent sessions with edit/delete/restart actions per row.

---

## 3. PRIOR ART TO AVOID

The owner reviewed all five concepts in `design_concepts/` and rejected **every one**. Do not
resubmit a variation of any of them.

**1 · Almanac** — Light warm paper on `#f5efe3` with ink `#2b2620`, oxblood `#7d3b30`, ochre
`#c1892f`, moss `#5d6b4d`. Serif body (Source Serif 4 / Fraunces italic display) with IBM Plex
Mono only for labels and timestamps. Sessions rendered as ruled journal entries on "Today's
page" with margin-aligned time ranges, small-caps project labels, faded rule lines, and a
pulsing dot for running timers. Framed time tracking as a naturalist's field log rather than a
dashboard. Rejected: it is light-first, it abandons the dark base entirely, and there is nowhere
for the backdrop image to live.

**2 · Terminal Roots** — Full TUI. Warm near-black `#14120d`, phosphor amber `#e8a33d`, dim
`#9a927f`, bright `#e8e2d2`, leaf-red `#c4553e`, sage `#8ea87c`, pane lines `#3a352a`. JetBrains
Mono for *everything*, no proportional type at all. Layout as opaque tmux-style panes with box-
drawing headers, a command palette docked at the bottom bound to `/`, a live ticking timer, and
ASCII bar charts for totals. Pitched as honouring Autumn's CLI heritage. Rejected: the opaque
full-bleed panes destroy the background-image feature, and all-mono at every level flattens
hierarchy.

**3 · Canopy** — Glassmorphism. Translucent `rgba(16,20,22,0.62)` panels with backdrop blur
floating over the user's backdrop, generous gutters, text `#eef0ea`, accent `#e0a458`, Sora/
Outfit display over Inter body. Signature element is a huge centred hero timer with a circular
SVG progress ring; running sessions glow softly. Positioned as the "modern calm focus app."
**This is the one the owner called "boring and more or less what I already have"** — the current
cards already run `backdrop-filter: blur(8px)` at 90 % opacity, so frosted glass reads as a
lateral move, not a redesign.

**4 · Harvest Board** — Editorial magazine dashboard on deep forest green: base `#1c2620`, panels
`#243029`, cream text `#e6e4d5`, muted `#93a08f`, harvest gold `#d9a441`, ember `#c05b43`, leaf
`#7fa06a`, hairlines at 12 % cream. Instrument Serif / Libre Caslon italic display against
Archivo for data, tabular numerals throughout. Anchored by a GitHub-style 7×16 contribution
heatmap of the last 16 weeks and one enormous serif-italic monthly total, with everything else
reduced to quiet rules. Rejected: the green base fights the red/blue/green semantic text set, and
the giant-stat-plus-heatmap thesis serves reporting rather than the daily start/stop/log loop.

**5 · Acrylic Terminal** — Explicit hybrid of 2 and 3: the TUI *inside* the glass. Panes are
translucent terminal windows (`rgba(18,16,12,0.68)` + blur, hairline `rgba(232,226,210,0.14)`)
floating over the backdrop the way a transparent iTerm2 window does, JetBrains Mono exclusively
with hierarchy carried by weight, letter-spacing and phosphor amber `#e8a33d`. Signature is the
docked glass command palette (`autumn ❯`, `/` to focus) plus a hero running timer in giant thin
mono digits inside a tmux-titled pane. Rejected along with its two parents.

### Off the table — do not use these moves
- **Frosted-glass / glassmorphism panels.** Blur-behind translucent cards are already shipped; more of it is not a redesign. (If you use translucency at all, it must be doing something the current CSS does not.)
- **Terminal / CLI chrome.** No box-drawing pane borders, no tmux title bars, no `❯` prompt, no docked command palette as the organising idea, no all-monospace type system, no ASCII bar charts. Mono stays confined to numerals and durations.
- **Kanban / column boards.** No drag-between-columns status boards for projects or sessions.
- **Paper, almanac, journal or parchment textures.** No cream/ecru paper base, no ruled-margin journal metaphor, no serif-italic editorial display type as the primary voice.
- **Light-first anything.** See §2.3.

The gap none of the five filled: something that is unmistakably dark, that *uses* the backdrop
image as an active design element rather than merely tolerating or hiding it, that keeps the six
semantic hues legible, and that makes the daily loop — start a timer, stop it, scan today's rows
— faster than it is now. Aim there.

---

## 4. Current pain points to solve

**Heavy inline styles in `dashboard.html`.** 30 `style="..."` attributes across 310 lines. Layout
grids (`display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr))`), spacing
(`margin-bottom:1.5rem`), typography (`font-weight:bold; font-size:1.1em`) and even *state
colours* live in markup — the streak-square span at L105 is a ~600-character inline style with a
four-branch Django `{% if %}` chain choosing between `--main-yellow` / `--main-cyan` /
`--main-green` / `--main-red`. The v2 design must be expressible as named classes so this can be
lifted out. Give every repeated element a real class name in your mockup.

**Card-in-card nesting.** `.card` is used as both page section and list item, so it stacks inside
itself. Commitments are `.card` items inside a section, each overriding the card background to
`rgba(0,0,0,0.5)` inline just to re-establish contrast against its parent. Every session row is
its own `.card` with a full border, shadow and `backdrop-filter: blur(8px)` — so a 20-session day
renders 20 blurred, bordered, shadowed boxes stacked 0.5 rem apart. Visually noisy and expensive.
V2 needs a clear two-tier surface model: a container treatment and a row treatment that are
*different things*, with rows as rules or bands rather than nested boxes.

**Fixed sidebar eating horizontal width.** `.left-panel` is `position: fixed`, `width: 14.5rem`
(13.5 rem under 1200 px), and `.main-body` pays for it with a matching `margin-left` — permanently,
on every page, for eight links that never change. It also `overflow: auto` at
`height: calc(100vh - 4.25rem)`. There is no collapse-to-icons state on desktop; the only escape
is the `max-width: 975px` breakpoint where it becomes a burger drawer. Content that wants width
(charts, the sessions list, the allocation editor) is squeezed. Consider a rail, an icon-collapse,
or moving navigation into the ribbon.

**Dense one-line session rows that rely on hover-sliders.** `.session-row` is a wrapping flex
line carrying: start time, "to", end time, duration, optional DST badge, project name, a
bracketed comma-joined subproject list, an arrow, the markdown-rendered note, and three icon
buttons pushed right by `margin-left:auto`. Project names and notes are clipped to
`min(34rem, 45%)` inside `.project-name-slider` / `.session-note-slider` with
`overflow:hidden; white-space:nowrap`. Overflowing notes are then **auto-scrolled forever** by
`session_sliders.js`, a jQuery `animate()` marquee that recurses on completion — perpetual motion
on the page, unreadable while moving, and it ignores `prefers-reduced-motion` (the media query at
L1193 does not cover it). The project-name slider is commented out in that file, so long project
names simply truncate with no ellipsis. **Do not design another marquee.** Give notes and long
names a real home: a second line, a truncation with tooltip/expand, a hover card, or a wider
column. Assume long project names, 3+ subprojects, and multi-sentence markdown notes are normal.

---

### Quick checklist for a v2 concept
- [ ] Dark base, works with a photo behind it at any dim level from 0.1 to 0.9
- [ ] Red = project, blue = subproject, green = duration, cyan = time, yellow = note, orange = brand
- [ ] Not glass, not a terminal, not a kanban, not paper
- [ ] Session rows readable at 20+ per day with long names and notes, no marquee
- [ ] Nav does not permanently cost ~14 rem of width
- [ ] One surface treatment for containers, a different one for rows — no card-in-card
- [ ] Every visual decision expressible as a class, not an inline style
- [ ] Survives 975 px and 12 px base font
