# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Autumn is a Django-based time and project tracking web application. It's the browser-accessible version of the [Autumn CLI](https://github.com/Fingolfin7/Autumn), with import/export compatibility between the two.

## Commands

```bash
# Create/activate virtual env (optional but recommended)
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate

# Development server (Django renders the page shell; the UI is the React app in frontend/)
python manage.py runserver

# Web UI (frontend/, Node 22)
cd frontend && npm ci
npm run dev        # Vite on :5173; run Django with VITE_DEV_SERVER=http://localhost:5173 for hot reload
npm run build      # Writes core/static/app/ (gitignored); Django serves it when VITE_DEV_SERVER is unset
npm run gen:api    # Regenerate src/api/schema.d.ts after changing openapi-v2.yaml
npm run typecheck && npm test

# Database migrations
python manage.py makemigrations
python manage.py migrate

# Run all tests
pip install -r requirements-dev.txt
python manage.py test
node --test scripts/tests/polling.test.cjs scripts/tests/recommendations.test.cjs scripts/tests/charts_related.test.cjs

# Run specific test file
python manage.py test core.tests.test_parse_date_or_datetime_iso

# Custom management commands
python manage.py audit --username=<user>  # Recalculate totals (omit --username for all)
python manage.py export <username> --output_file=<path>
python manage.py import <username> --input_file=<path>
python manage.py clear --username=<user>  # Delete all project data (omit --username for all users)
python manage.py clear_temp_uploads --older-than-hours=24 [--dry-run]  # Sweep abandoned import uploads from MEDIA_ROOT/temp
python manage.py embed_sessions [--username=<user>] [--dry-run] [--limit=N]  # Embed new/changed sessions and projects for semantic search (backfill/repair; web processes do it after edits)
python scripts/semantic_search_eval.py [--keyword-only]  # Keyword vs hybrid search on fictional records; needs OPENAI_API_KEY
```

## Architecture

### Web UI (frontend/)

The browser UI is a React 19 + TypeScript single-page app in `frontend/` (Vite, react-router, TanStack Query, openapi-fetch). It talks only to `/api/v2/`; its client types are generated from `openapi-v2.yaml` (`npm run gen:api`), so API changes go through the schema first.

- Django still owns every URL: each page route in `core/urls.py` (and `profile/`, `insights/`) points at `core.spa.spa`, which renders `core/templates/core/spa.html` with the Vite bundle from `core/static/app/manifest.json` and a JSON bootstrap blob (`bootstrap_payload`: user, profile defaults, contexts, CSRF token, flash messages). Unknown paths are real 404s, and auth pages (login, register, password reset, OAuth) stay server-rendered.
- Adding a page means an entry in `frontend/src/app/routePatterns.ts` and a Django route to `spa` under the same path, keeping the old URL name.
- Pages live in `frontend/src/features/<area>/`; shared shell, toasts, command palette and offline sync in `frontend/src/app/`. The Night Ledger look comes from `core/static/core/css/focus_desk.css`, loaded by `spa.html`; `frontend/src/styles/app.css` only adds what the app introduces.
- Offline: TanStack Query's cache is persisted to localStorage, timer start/stop made offline are queued (`frontend/src/lib/offlineQueue.ts`) and replayed when the server is reachable, and the service worker (`core/static/core/pwa/service-worker.js`) keeps the app shell and built assets.
- Render builds with `bash scripts/render-build.sh` (pip install, `npm ci && npm run build`, collectstatic).

### Django Apps

- **core/** - Main app: Projects, SubProjects, Sessions, timers, charts, data visualization
- **users/** - Authentication, user profiles, encrypted API key storage
- **llm_insights/** - LLM chat integration (Gemini, OpenAI, Claude)

### Data Model Hierarchy

```
User → Context → Projects → SubProjects → Sessions
```

- **Context**: Activity scopes (Work, Personal, Study)
- **Projects**: Parent containers with status (active/paused/complete/archived)
- **SubProjects**: Child tasks within projects
- **Sessions**: Time records with start/end times, notes, and subproject references
- Sessions have many-to-many relationships with both Projects and SubProjects

### API Structure (core/api_v2/)

Two API styles coexist:

1. **Compact endpoints** (CLI-optimized): `/api/timer/start/`, `/api/timer/stop/`, `/api/track/`, `/api/totals/`, `/api/commitments/`, etc.
   - Default `compact=true` uses abbreviated keys (`p`, `subs`, `dur`, `elapsed`)
   - Pass `?compact=false` for expanded responses

2. **Project/context/tag management**: `/api/project/update/`, `/api/contexts/`, `/api/contexts/<id>/`, `/api/tags/`, and `/api/tags/<id>/`; `/api/create_project/` also accepts context and tags.

3. **Import**: `POST /api/import/` accepts export JSON (or compressed JSON) and shares its import logic with the streaming web import flow.

4. **Legacy endpoints**: `/api/create_project/`, `/api/start_session/`, etc.

All API endpoints require authentication (session or token) except `GET /healthz/`, an unauthenticated root health check used to probe or wake sleeping deployments. Durations are in **minutes** (float). The versioned `/api/v2/` surface is documented in `openapi-v2.yaml`; the legacy `/api/` surface is documented in `docs/api.md`.

### LLM Handler Pattern (llm_insights/)

Pluggable handler architecture with a base class:
- `base_handler.py` - Abstract base
- `gemini_handler.py` - Google Gemini (uses the user's profile key)
- `openai_handler.py` - OpenAI (user-provided key only)
- `claude_handler.py` - Anthropic Claude (user-provided key only)

User API keys are encrypted with Fernet (derived from `SECRET_KEY`) and stored in the Profile model as BinaryFields.
Rotating `SECRET_KEY` will invalidate existing encrypted keys unless you migrate/re-encrypt them.

### Key Files

- `core/views/` - UI views package, one module per area (`timers`, `sessions`, `projects`, `contexts_tags`, `commitments`, `import_export`, `charts`, `dashboard`); import views from their owning module rather than relying on package-level re-exports
- `core/api_v2/` - versioned REST API package (`views`, `serializers`, `reports`, `commitments`, `contexts_tags`, `filters`, `import_export`); `openapi-v2.yaml` is the checked-in schema artifact
- `core/importer.py` - Shared `iter_import` generator and `run_import` wrapper used by web and API imports
- `core/temp_uploads.py` - Staging of web-import uploads under `MEDIA_ROOT/temp` between the import POST and the stream GET, plus their cleanup
- `core/services/semantic_search.py` - meaning-based search: OpenAI `text-embedding-3-small` (512 dims) vectors in `SessionEmbedding`/`ProjectEmbedding`, written with each user's own OpenAI key while `ai_features_enabled`, by `core/services/embedding_sync.py` (a daemon thread in each web process re-embeds an account ~10 s after edits, requested via `core/signals.py` and `request_sync_on_commit` on `update()` paths that bypass signals; related searches also recheck an account every 10 min) and by `embed_sessions` for backfills; a search embeds just the query and falls back to keyword results on any failure. A vector is stale when its stored text digest no longer matches the record's current text (project/subproject names plus the note or description). Notes longer than one ~240-character passage also get per-passage vectors (`SessionPassageEmbedding`, replaced together under one digest of the session's text), and a session scores the better of its whole vector and its best passage. Sessions search is one ranked list shared by the Sessions page and API v2/MCP (`core.search.rank_sessions`: direct keyword matches newest first, then every related match above the cutoff best first; the API's default `ordering=relevance` returns that order with a per-row `match`, and the page shows related matches in their own paged "Related" section). Projects shows a separate 5-item "Related" section; Charts and Insights count related sessions only with the "Include related sessions" toggle (`related=on`); API v2 sessions/reports/projects take `search` + `related=true` and answer with an `X-Autumn-Related: included|unavailable` header (Charts' JS flips its "Including related" pill from it; Insights does the same server-side). A failed query embedding starts a 5-minute per-account cooldown (`FAILURE_COOLDOWN_SECONDS`). `core.search.search_sessions(..., user=, related=)` applies it and must run after every other filter, since related matches are drawn from what the filters left
- `core/urls.py` - URL routing, including `/healthz/`
- `core/utils.py` (~20KB) - Helper functions, date parsing, data formatting
- `users/models.py` - Profile model with encrypted API key get/set methods
- `autumn_mcp.py` - MCP server for Claude Code integration

## Environment Variables

Required in `.env`:
```
SECRET_KEY=<django-secret>
DEBUG=TRUE/FALSE
```

Optional:
```
DATABASE_URL=postgres://...  # Falls back to SQLite
NASA_API_KEY=<key>
SERVE_MEDIA=TRUE  # For PaaS deployments
VITE_DEV_SERVER=http://localhost:5173  # Dev only: load the UI from Vite instead of the built bundle
ALLOWED_HOSTS=autumn.example.com,localhost  # Comma-separated; defaults to *
ALLOW_REGISTRATION=FALSE  # Registration is closed unless explicitly enabled
GOOGLE_OAUTH_CLIENT_ID=<google-web-client-id>
GOOGLE_OAUTH_CLIENT_SECRET=<google-web-client-secret>
GITHUB_OAUTH_CLIENT_ID=<github-oauth-client-id>
GITHUB_OAUTH_CLIENT_SECRET=<github-oauth-client-secret>
PUSH_VAPID_PUBLIC_KEY=<base64url public key>
PUSH_VAPID_PRIVATE_KEY=<private key secret; never commit>
PUSH_VAPID_SUBJECT=mailto:admin@example.com
PUSH_ALLOWED_ENDPOINT_SUFFIXES=fcm.googleapis.com,push.services.mozilla.com,notify.windows.com,push.apple.com
RUN_REMINDER_DISPATCHER=FALSE  # TRUE runs the dispatcher thread inside the web process
SEMANTIC_SEARCH_MIN_SIMILARITY=0.45  # Cosine cutoff for Sessions "Related" results
SEMANTIC_SYNC_ON_WRITE=TRUE  # Background re-embedding after edits in web processes
PUSH_DISPATCH_SAFETY_RESCAN_SECONDS=900  # Durable fallback; minimum 300 seconds
PUSH_MAX_ATTEMPTS=5  # Maximum attempts per device before terminal failure
PUSH_RETRY_BASE_SECONDS=30  # Exponential-backoff base for transient failures
```

Google and GitHub buttons are enabled independently when both credentials for
that provider are set. See `docs/social-auth.md` for provider setup and callback
URLs. Run `python manage.py migrate` after installing or updating dependencies.

Timer reminder delivery is optional and has two modes, both running the shared
`run_dispatch_pass` in `core/services/reminder_dispatcher.py` under the same
best-effort cache lock:

- the bounded `python manage.py dispatch_timer_reminders --once` cron command
  (or `--loop --max-seconds 30` locally); and
- an opt-in daemon thread enabled by `RUN_REMINDER_DISPATCHER=TRUE`.
  `CoreConfig.ready()` starts it for runserver/uvicorn/daphne; Gunicorn uses
  `post_worker_init` so the thread starts after the worker fork. It scans
  persisted deadlines at startup,
  sleeps until work is due, wakes on relevant local commits, and performs an
  infrequent safety rescan (default 900 seconds, minimum 300) for external or
  bulk writes. `should_start_dispatcher` gates it to web processes only
  (`runserver` autoreload child or
  `--noreload`, plus uvicorn/daphne; Gunicorn is gated by its worker hook); no
  management command,
  `test`/`migrate`/`check` included, ever starts it.

The VAPID private key remains server-only; browser test notifications are
queued for the dispatcher rather than sent from a request.

Each dispatch writes an INFO `notification_dispatch` record through the
`core.services.push` logger. It includes event/user identity, scheduled time,
overall status, targeted/delivered/pending/failed/expired/unavailable device
counts, attempts, and `provider_accepted_at`. Provider/device failures also
write `notification_device_failure` WARNING records. Render captures these
console logs; filter by logger name or search for `notification_dispatch`.
Provider acceptance confirms that the push service accepted the request, not
that the operating system displayed it.

## Database Notes

- Development: SQLite (`db.sqlite3`)
- Production: PostgreSQL supported via `DATABASE_URL`
- PostgreSQL returns `memoryview` for BinaryFields - convert to `bytes()` before Fernet decryption

## Testing

Tests are in `core/test_*.py`, `core/tests.py`, `users/`, and `llm_insights/`.
Install `requirements-dev.txt` for test-only dependencies. CI runs on Windows
with SQLite and Python 3.10, and Ubuntu with PostgreSQL and Python 3.13.
Browser polling behavior tests use Node 22+ built-ins, with no npm dependencies.
Frontend tests are Vitest (`npm test` in `frontend/`); CI also checks that
`src/api/schema.d.ts` matches `openapi-v2.yaml`, type-checks and builds the app.
