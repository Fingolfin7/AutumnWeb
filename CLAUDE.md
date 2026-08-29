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

# Development server
python manage.py runserver

# Database migrations
python manage.py makemigrations
python manage.py migrate

# Run all tests
python manage.py test

# Run specific test file
python manage.py test core.tests.test_parse_date_or_datetime_iso

# Custom management commands
python manage.py audit --username=<user>  # Recalculate totals (omit --username for all)
python manage.py export <username> --output_file=<path>
python manage.py import <username> --input_file=<path>
python manage.py clear --username=<user>  # Delete all project data (omit --username for all users)
python manage.py clear_temp_uploads --older-than-hours=24 [--dry-run]  # Sweep abandoned import uploads from MEDIA_ROOT/temp
```

## Architecture

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

### API Structure (core/api/)

Two API styles coexist:

1. **Compact endpoints** (CLI-optimized): `/api/timer/start/`, `/api/timer/stop/`, `/api/track/`, `/api/totals/`, `/api/commitments/`, etc.
   - Default `compact=true` uses abbreviated keys (`p`, `subs`, `dur`, `elapsed`)
   - Pass `?compact=false` for expanded responses

2. **Project/context/tag management**: `/api/project/update/`, `/api/contexts/`, `/api/contexts/<id>/`, `/api/tags/`, and `/api/tags/<id>/`; `/api/create_project/` also accepts context and tags.

3. **Import**: `POST /api/import/` accepts export JSON (or compressed JSON) and shares its import logic with the streaming web import flow.

4. **Legacy endpoints**: `/api/create_project/`, `/api/start_session/`, etc.

All API endpoints require authentication (session or token) except `GET /healthz/`, an unauthenticated health check used to probe or wake sleeping deployments. Durations are in **minutes** (float).

### LLM Handler Pattern (llm_insights/)

Pluggable handler architecture with a base class:
- `base_handler.py` - Abstract base
- `gemini_handler.py` - Google Gemini (uses the user's profile key)
- `openai_handler.py` - OpenAI (user-provided key only)
- `claude_handler.py` - Anthropic Claude (user-provided key only)

User API keys are encrypted with Fernet (derived from `SECRET_KEY`) and stored in the Profile model as BinaryFields.
Rotating `SECRET_KEY` will invalidate existing encrypted keys unless you migrate/re-encrypt them.

### Key Files

- `core/views/` - UI views package, one module per area (`timers`, `sessions`, `projects`, `contexts_tags`, `commitments`, `import_export`, `charts`, `dashboard`); `__init__.py` re-exports every view so `from core.views import X` still works
- `core/api/` - REST API package, same layout (`helpers`, `timers`, `sessions`, `projects`, `subprojects`, `tallies`, `commitments`, `contexts_tags`, `import_export`, `misc`); `__init__.py` re-exports every endpoint
- `core/importer.py` - Shared `iter_import` generator and `run_import` wrapper used by web and API imports
- `core/temp_uploads.py` - Staging of web-import uploads under `MEDIA_ROOT/temp` between the import POST and the stream GET, plus their cleanup
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
RUN_AUDIT_SCHEDULER=FALSE
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
```

Google and GitHub buttons are enabled independently when both credentials for
that provider are set. See `docs/social-auth.md` for provider setup and callback
URLs. Run `python manage.py migrate` after installing or updating dependencies.

Timer reminder delivery is optional and runs only through the bounded
`python manage.py dispatch_timer_reminders --once` cron command (or
`--loop --max-seconds 30` locally); no scheduler is started from
`AppConfig.ready()`. The VAPID private key remains server-only; browser test
notifications are queued for the dispatcher rather than sent from a request.

## Database Notes

- Development: SQLite (`db.sqlite3`)
- Production: PostgreSQL supported via `DATABASE_URL`
- PostgreSQL returns `memoryview` for BinaryFields - convert to `bytes()` before Fernet decryption

## Testing

Tests are in `core/tests.py` and `core/tests/`. CI runs on GitHub Actions (Windows, Python 3.10/3.13).
