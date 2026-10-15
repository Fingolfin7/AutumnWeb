# Autumn web: TypeScript + React rewrite plan (`ts-react`)

Status: in progress on branch `ts-react` (branched from `master` at 06b8dd7).
Owner: Henry. Orchestrated by Claude; backend chunks delegated to Codex
`gpt-5.6-sol`, frontend page ports to Claude Sonnet subagents, architecture,
specs and verification kept with the orchestrator.

## 1. Goal

Replace the server-rendered Django templates + hand-written JS with a
TypeScript React single-page app that talks only to a documented JSON API,
without losing anything the current web app does, and use the rewrite to make
Autumn faster and nicer on phone and desktop.

Hard constraints:

- **Keep the Night Ledger look.** Same tokens, palette (#101214 / #c98245),
  semantic text colours (projects red, subprojects blue, durations green), the
  sidebar/tab bar + sheet shell, and the user background-image feature. The
  React app starts from `focus_desk.css` as-is. Additive components are fine;
  restyling is not.
- **The CLI and the MCP (Claude + ChatGPT) must keep working unchanged.**
  `/api/v2/` stays backward compatible: new endpoints and new optional fields
  only. `openapi-v2.yaml` stays the single contract and the CI diff gate stays.
- **No feature regressions.** Every page and action in §6 has a checklist row;
  the old template is deleted only when its row is ported and verified.
- **Public repo:** no real session data in fixtures, screenshots or tests.

Non-goals: native apps, a new design language, a GraphQL layer, SSR/Next.js.

## 2. Concerns raised before the rewrite, and how this plan answers them

| Concern | Answer in this plan |
|---|---|
| API v2 does not cover what the web app needs (dashboard, timeline, Luna recommendations, insights chat, notifications/push, weekly review, settings, MCP connections, context switch, streaming import) | §4 inventories every gap and specifies the endpoint that closes it. Backend phase B1 lands before the pages that need it. |
| MCP tools are generated from every OpenAPI operation, so new web endpoints would silently become MCP tools | §5: an explicit `x-autumn-mcp` include/exclude marker per operation, enforced by `integrations/mcp/scripts/build.mjs` and a test that pins the tool list. New *useful* tools (weekly review, recommendations, reminders) are added deliberately. |
| Monolith views (`core/views/timers.py` 931 lines, `llm_insights/views.py` 1283, `core/api_v2/views.py` 1476, `core/forms.py` 1075) | §7: logic moves into `core/services/*` first (behaviour-preserving, baseline-diffed), API views split into a package by resource, template views + forms deleted at cutover. |
| "Overnight" code is not verified parity | §6 checklist per page, Vitest unit tests, Playwright smoke flows on fictional data, Django API tests for every new endpoint, and a browser pass on phone and desktop sizes before calling it ready. |
| Auth, CSRF, social login, OAuth consent are security-sensitive | Login/register/social/password pages, the MCP OAuth authorize/link pages and the admin stay server-rendered Django (§3.4). The SPA uses same-origin session cookies + CSRF header; no tokens in JS. |
| Two toolchains, Node build on Render | §9: one `frontend/` package, built into Django static by `npm run build`; Render build command gains the npm step (needs confirmation before merge). CI builds, type-checks and tests the frontend. |
| Resource use on a 1-worker/4-thread Render starter | §8: JSON + ETag/304 polling instead of 5 s HTML fragment renders, one poller shared across tabs, no long-lived SSE except Insights streaming. Static assets hashed + immutable. |

## 3. Architecture

### 3.1 Frontend stack

- **React 19 + TypeScript (strict) + Vite.** Package lives in `frontend/`.
- **Routing:** React Router (library mode, `createBrowserRouter`), lazy route
  modules so Charts and Insights don't load on Home.
- **Server state:** TanStack Query. One query-key factory per resource;
  mutations invalidate/patch precisely; optimistic updates for timers and notes.
- **API client:** `openapi-typescript` generates `src/api/schema.d.ts` from
  `openapi-v2.yaml`; `openapi-fetch` gives a typed client. A thin wrapper adds
  the CSRF header, the `{"error": {code, message, details}}` envelope → typed
  `ApiError`, and 401/403-to-login redirect. `npm run gen:api` regenerates; CI
  fails if the generated file is stale.
- **Charts:** Chart.js 4 from npm (pinned), only the registered controllers we
  use, `chartjs-chart-matrix`, `chartjs-chart-treemap`,
  `chartjs-adapter-date-fns` (moment.js and jQuery UI go away), `wordcloud`
  from npm. Charts route is code-split.
- **Icons:** Font Awesome icons we actually use via
  `@fortawesome/react-fontawesome` + per-icon imports (same glyphs, no
  render-blocking CDN, a fraction of the bytes).
- **Markdown:** the server keeps rendering + nh3-sanitising notes and Insights
  replies (one sanitiser, already reviewed). The API returns `note_html` when
  asked; the client never builds HTML from user text.
- **Styling:** `focus_desk.css` imported globally at first (exact parity), then
  component-local styles where a component is genuinely new. Design tokens stay
  CSS custom properties.
- **Tests:** Vitest + Testing Library for logic and components; Playwright for
  end-to-end smoke flows against a dev server seeded with fictional data.

### 3.2 Folder layout

```
frontend/
  index.html               Vite entry (dev only; prod uses Django's spa.html)
  vite.config.ts           base=/static/app/, manifest, proxy → :8000 in dev
  src/
    main.tsx               boot: bootstrap JSON, QueryClient, router
    api/                   schema.d.ts (generated), client.ts, errors.ts, keys.ts
    app/                   Shell (header, tab bar, More sheet), routes.tsx,
                           providers, toasts, command palette
    features/<area>/       timers, sessions, projects, charts, commitments,
                           insights, notifications, settings, contexts-tags,
                           import-export, dashboard
    components/            shared UI: OptionPicker, ProjectSearch, Duration,
                           LocalTime, NoteEditor, AllocationEditor, Sheet,
                           ConfirmDialog, EmptyState, Skeleton
    lib/                   time formatting, durations, distribute(), storage,
                           broadcast channel, polling, offline queue
    styles/                focus_desk.css (moved from core/static), additions
  tests/                   Vitest unit + component tests
  e2e/                     Playwright specs
```

### 3.3 How Django serves it

- `npm run build` writes hashed assets + `manifest.json` into
  `core/static/app/` (gitignored build output); `collectstatic` + WhiteNoise
  serve them with far-future caching.
- `core/spa.py` renders `core/templates/core/spa.html`: the manifest's entry
  `<script>`/`<link>` tags, a `<script id="autumn-bootstrap"
  type="application/json">` blob (user, profile display prefs, contexts, active
  context, feature flags, CSRF token, static version) so first paint needs no
  extra request, and the background-image `<body>` style the shell already
  computes (Bing/APOD resolution stays server-side).
- Each ported page's route in `core/urls.py` keeps its URL name but points at
  the `spa` view (unauthenticated → login with `next`). There is no catch-all:
  an unknown path is a real server 404, so removed routes (e.g. the old debug
  probes) stay gone. A new React-only page needs its Django route too.
- **Dev:** `VITE_DEV_SERVER=http://localhost:5173` makes `spa.html` load from
  Vite with HMR; Django still owns cookies, CSRF and auth.

### 3.4 What stays server-rendered (on purpose)

Login, logout, register, password change/reset, allauth social login/connect
screens, MCP OAuth `authorize` / `link account` / `connections`, the Django
admin, API docs. They keep a slim `base_auth.html` using the same stylesheet,
so they still look like Autumn. Rationale: consent and credential pages should
not depend on client JS, and allauth/oauth-toolkit own their flows.

## 4. API gaps and the endpoints that close them

All new endpoints live under `/api/v2/`, are documented by drf-spectacular,
use the existing error envelope and ETag/If-Match conventions, and get Django
API tests. "MCP" column: whether it becomes an MCP tool (§5).

| Web need (current source) | New/changed endpoint | MCP |
|---|---|---|
| Who am I + preferences (base.html, profile) | extend `GET /me/` (profile display prefs, contexts, active context, feature flags, ai flags); `PATCH /me/preferences/` (timezone, default filters, chart project count, dimming, background mode, Luna effort, ai_features_enabled, active context) | `me` only (read) |
| Profile secrets (API keys, ChatGPT/Codex device login) | `PUT/DELETE /me/api-keys/<provider>` (write-only, returns `{configured: bool}`), `POST /me/codex-login/` start + poll | no |
| Avatar + background image upload, background download | `PUT /me/avatar`, `PUT/DELETE /me/background` (multipart), `GET /me/background/current` | no |
| Social accounts (profile) | `GET /me/social-accounts/`, `DELETE /me/social-accounts/<provider>` | no |
| Active context (session-stored) | stored on Profile (`active_context`), set via `PATCH /me/preferences/`; every list/report endpoint already takes `context` filters; the SPA passes it explicitly | no |
| Dashboard (DashboardView: streak, commitments panel, recent sessions grouped, quick starts, active timers, timeline) | `GET /dashboard/` one aggregate payload for first paint on phones | yes (`get_dashboard`, read) |
| Day timeline fragment | `GET /reports/timeline/?start&end` | yes (read) |
| Timer suggestions (recent/habit/commitment) + Luna recs + usage + refresh | `GET /recommendations/timers/` (fast heuristics), `GET /recommendations/luna/` (202 + Retry-After while computing), `POST /recommendations/luna/refresh/`, `POST /recommendations/usage/` | heuristics + luna read: yes; refresh/usage: no |
| Timer note autosave | exists (`PATCH /timers/{id}` note) | exists |
| Timer reminders (cancel per timer) | `GET /timers/{id}/reminders/`, `DELETE /timers/{id}/reminders/{rid}` | no |
| Notifications page (preferences, scheduled reminders edit/snooze/cancel) | `GET/PATCH /notifications/preferences/`, `GET/POST /notifications/schedules/`, `PATCH/DELETE /notifications/schedules/{id}`, `POST .../{id}/snooze/` | schedules list/create: yes |
| Push (status/subscribe/unsubscribe/test) | `GET /push/status/`, `POST /push/subscriptions/`, `DELETE /push/subscriptions/`, `POST /push/test/` | no |
| Weekly review | `GET /reports/weekly-review/?week=` | yes (`weekly_review`) |
| Insights chats (list, detail, delete, stream) | `GET /insights/chats/`, `GET/DELETE /insights/chats/{uuid}`, `POST /insights/chats/stream/` (SSE, same event names as today) | no (the MCP client *is* an LLM) |
| Streaming import with progress | `POST /import/uploads/` (stage file → upload id) + `GET /import/uploads/{id}/stream/` (SSE progress, reuses `iter_import`); existing `POST /import/` unchanged | no |
| Export form options | exists (`GET /export/`); add form-option metadata if missing | exists |
| Projects list grouping/status/stats, project + subproject edit, merge | mostly exists; add any missing fields found during port (description, tags, context, status counts, sidebar stats) | exists |
| Sessions page (filters, related section, paging) | exists (`ordering=relevance`, `match`); add `include=note_html` | exists |
| Commitment form metadata (scope meta, rule dimensions) | `GET /commitments/form-options/` | no |
| Charts | exists (`/reports/charts/`); keep legacy shapes, typed on the client | exists |
| Contexts / tags CRUD | exists | exists |

Backend services each page needs already exist in `core/services/*`; the new
endpoints must call them rather than re-implement logic.

### 4.1 Gaps found while porting (backend chunk 3)

- `GET /commitments/?applies_to=<kind>:<id>` using `core.commitments.commitment_applies_to_*`,
  so the project/subproject/context/tag pages stop carrying two TypeScript
  copies of those rules (`projects/logic.ts`, `commitments/applies.ts`) and
  share one panel component.
- Projects list: search across descriptions/subproject names, date-range and
  activity ordering; subproject `start_date`; `version` + `If-Match` on
  projects and subprojects.
- Commitments: `current_surplus` and consistent filter names.
- `GET /sessions/{id}?include=note_html`; an `id` filter on the sessions list.
- Charts: complete the `chart_type` enum, type `context` as an id, and give
  the chart responses real schemas.
- Bootstrap/`/me/`: default chart date range, whether an OpenAI key is set.
- DST-ambiguous local times in start/stop/edit forms: reject or disambiguate
  the way the Django forms did.

## 5. MCP: keeping ChatGPT/Claude stable and making it better

- `build.mjs` currently turns *every* OpenAPI operation into a tool. Add a
  required vendor extension `x-autumn-mcp: include | exclude` (set via
  `extend_schema(extensions=...)`), make `build.mjs` honour it and fail if an
  operation lacks it. Existing 46 operations are marked `include` → tool list
  unchanged.
- New test pins the generated tool name list (snapshot) so a backend change
  can't silently add/remove tools. `core.test_mcp` / `core.test_mcp_oauth`
  must stay green.
- Deliberate new tools: `get_dashboard`, `get_timeline`, `weekly_review`,
  `timer_suggestions`, `luna_recommendations`, `list/create reminder
  schedules`. Each gets a hand-written description in `build.mjs`.
- Never exposed: secrets, push, uploads, insights, preferences writes.

## 6. Page inventory and port checklist

Each row: port → parity check (desktop + phone width) → delete template/view
→ tick. Improvements listed are in scope for the port.

| Page (URL) | Current pieces | Port notes + improvements |
|---|---|---|
| Shell (base.html) | header, context switch, dimming slider, avatar, tab bar, More sheet, messages, background, PWA | React shell; toast system replaces Django messages (incl. celebration toasts); context switch is instant (no reload); live elapsed of first running timer in the tab title; Ctrl/⌘-K command palette (start timer, jump to project/page, search sessions) |
| Home `/` | DashboardView, dashboard_desk.js, timer_poll.js, timeline fragment, commitments panel, quick starts, activity range | one `/dashboard/` request; focus cards tick from one clock; quick-start is one tap with optimistic card; timeline range switch without fetch storms |
| Timers `/timers/` | TimerListView, active fragments, Luna recs, reminders, notes autosave | shared timers store; note autosave with draft persistence; no dirty-editor guard needed (component owns its state) |
| Start timer `/start_timer/` | start form, project search, subproject resolution, recs | becomes a sheet/dialog reachable from anywhere (+ route kept); project/subproject combobox with keyboard nav; "start another" without leaving the page |
| Stop timer `/stop_timer/<id>/` | stop form, note, allocation editor | stop sheet with note + allocation editor; one-tap stop when no edits |
| Restart / remove timer | POST + confirm page | inline actions with undo toast instead of confirm pages where safe |
| Sessions `/sessions/` | filters, related section, paging, local times | URL-synced filters; infinite/“load more” paging; related section; inline note expand |
| Edit/delete session | update_session (int + uuid routes), allocation editor | edit sheet/page; uuid route kept |
| Projects `/projects/` | grouped list, status, stats, related section | grouped by status/context; inline status change; related section |
| Create/update/delete project, subproject; merge projects/subprojects | CBVs + forms | dialogs/pages on the v2 endpoints; merge flows with preview of resulting totals |
| Charts `/charts/` | 7 chart modules, filters, related pill | typed chart modules, URL-synced filters, code-split; keep every chart kind |
| Commitments create/update/delete | 500-600-line templates with inline JS | one `CommitmentForm` component for create + edit, form-options endpoint |
| Contexts `/contexts/`, Tags `/tags/` + update/delete | CBVs | inline create/rename/colour/delete |
| Insights `/insights/`, `/insights/<uuid>/` | SSE stream, chat list, delete, filters | streaming chat UI with the existing composer layout (Enter to send), abortable stream |
| Notifications `/notifications/` | preferences, schedules edit/snooze/cancel, push | same features on new endpoints; push permission flow in-app |
| Weekly review `/review/weekly/` | template | page on `/reports/weekly-review/` |
| Import `/import/` + stream, Export `/export/` | forms + SSE progress | upload with progress bar + streamed log; export downloads via v2 |
| Profile `/profile/` | user/profile forms, API keys, codex login, social accounts, background, dimming | settings page with sections; secrets write-only |
| MCP connections, OAuth pages, auth pages | server-rendered | stay server-rendered (§3.4), linked from Settings |

## 7. Backend refactors that come with it

Phase B0 (behaviour-preserving, baseline-diffed against the dev DB):

1. `core/views/timers.py` → move suggestion building (`build_timer_suggestions`,
   `_luna_suggestions`, habit/recent/commitment helpers) into
   `core/services/timer_suggestions.py`; the view becomes a thin caller.
2. `core/views/dashboard.py` helpers (quick starts, recent grouping, timeline)
   → `core/services/dashboard.py`.
3. `llm_insights/views.py` → `llm_insights/services/` (chat persistence,
   context building, streaming orchestration) + thin views.
4. `core/api_v2/views.py` → `core/api_v2/views/` package by resource
   (timers, sessions, projects, contexts_tags, me) with re-exports for urls.
5. Notifications/push view logic → services if not already there.

Phase B1: the endpoints in §4, each with tests, schema regenerated,
`x-autumn-mcp` markers, MCP build + tool snapshot updated.

Cut-over (Phase C): delete template views, templates, `core/forms.py` classes
with no remaining server-rendered consumer, `core/static/core/js/*`, the old
`scripts/tests/*.cjs` (replaced by Vitest equivalents), jQuery, the
`static_version` context processor (hashed assets replace it). View tests in
`core/tests.py` that cover deleted views are replaced by API tests of the same
behaviour.

## 8. Cross-cutting product improvements

- **Live timers without fragment polling.** One poller (leader tab via
  `BroadcastChannel`) GETs `/timers/` every 15 s while visible, with ETag →
  304; refetch on focus/online and after every mutation. All tabs share the
  result. Elapsed time ticks client-side from `start`. Cuts server work to a
  304 on most polls instead of a template render every 5 s per tab.
- **Optimistic actions** for start/stop/restart/note/quick-start with rollback
  + error toast; undo toasts for remove/delete where the API allows.
- **Offline-tolerant timers (phase F2).** Start/stop/note actions taken
  offline are queued in IndexedDB with client uuid + client timestamps (v2
  already accepts client instants and dedupes by uuid) and replayed on
  reconnect. Service worker caches the app shell so the PWA opens instantly
  and offline.
- **Speed on phone:** bootstrap JSON in the HTML, route-level code-splitting,
  initial JS budget ≤ 180 KB gzip (charts/insights excluded), skeletons instead
  of the page-loading overlay, stale-while-revalidate cache so revisiting a
  page is instant.
- **Command palette + shortcuts** (desktop): ⌘/Ctrl-K, `s` start, `.` stop
  latest, `/` search sessions.
- **Accessibility:** focus management for sheets/dialogs, aria-live for
  timers/toasts, keyboard-complete comboboxes.

## 9. Build, CI, deploy

- `frontend/package.json` scripts: `dev`, `build`, `typecheck`, `test`,
  `e2e`, `gen:api`, `lint`.
- CI (both OS jobs or Linux only for Node): `npm ci`, `gen:api` staleness
  check, `typecheck`, `test`, `build`; Django tests run after the build so
  `spa.html` tests can see a real manifest.
- Render: build command becomes
  `npm ci --prefix frontend && npm run build --prefix frontend && pip install -r requirements.txt && python manage.py collectstatic --noinput`.
  **Changing the Render service is outward-facing: confirm with Henry before
  merging.** Check `node --version` on the Render runtime first (one-off job).
- Rollback: the branch is merged only after cut-over; reverting the merge
  restores the template app (no schema change is required by the SPA except
  additive Profile fields).

## 10. Phases

| Phase | Content | Who |
|---|---|---|
| P0 | This plan; `frontend/` scaffold, typed client, shell, spa.html + catch-all, CI wiring | orchestrator |
| B0 | service extractions (§7) | Sol |
| B1 | new endpoints (§4) + MCP markers (§5) | Sol |
| F1 | pages in order: Home + Timers (+ start/stop sheets) → Sessions + edit → Projects (+ CRUD, merge) → Contexts/Tags → Commitments → Charts → Notifications + Weekly review → Insights → Import/Export → Settings | Sonnet agents per area, orchestrator integrates |
| F2 | offline queue, SW app-shell caching, command palette, polish | orchestrator + Sonnet |
| C | cut-over deletions, test migration, docs (CLAUDE.md, README) | Sol (backend) + orchestrator |
| V | full verification: Django suite, Vitest, Playwright, browser pass at 390 px and 1440 px, MCP tool snapshot, CLI smoke against dev server | orchestrator |

Commits are incremental (one per scaffold step, endpoint group, page).

## 11. Risks and open questions

- **Semantic-search branch** (`feature/semantic-search`, 1 commit ahead:
  per-search similarity) is not in this branch; it will need merging into
  `ts-react` (API param + the Sessions/Projects UI) before cut-over.
- **Render Node availability** — verify before changing the build command.
- **Service worker migration** — existing installs hold the v3 SW; the new SW
  must take over cleanly (bump cache names, keep push handlers identical).
- **Push notification click URLs** must keep resolving under the SPA routes.
- **Old bookmarks** (`/update_session/<id>/`, `/stop_timer/<id>/`, …) keep
  working as SPA routes with the same paths.
