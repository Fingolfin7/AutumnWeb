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

### API Structure (core/api.py)

Two API styles coexist:

1. **Compact endpoints** (CLI-optimized): `/api/timer/start/`, `/api/timer/stop/`, `/api/track/`, `/api/totals/`, etc.
   - Default `compact=true` uses abbreviated keys (`p`, `subs`, `dur`, `elapsed`)
   - Pass `?compact=false` for expanded responses

2. **Legacy endpoints**: `/api/create_project/`, `/api/start_session/`, etc.

All endpoints require authentication (session or token). Durations are in **minutes** (float).

### LLM Handler Pattern (llm_insights/)

Pluggable handler architecture with a base class:
- `base_handler.py` - Abstract base
- `gemini_handler.py` - Google Gemini (has server-side fallback key)
- `openai_handler.py` - OpenAI (user-provided key only)
- `claude_handler.py` - Anthropic Claude (user-provided key only)

User API keys are encrypted with Fernet (derived from `SECRET_KEY`) and stored in the Profile model as BinaryFields.
Rotating `SECRET_KEY` will invalidate existing encrypted keys unless you migrate/re-encrypt them.

### Key Files

- `core/views.py` (~60KB) - All UI views including timer, project, session management
- `core/api.py` (~53KB) - Complete REST API implementation
- `core/utils.py` (~20KB) - Helper functions, date parsing, data formatting
- `users/models.py` - Profile model with encrypted API key get/set methods
- `autumn_mcp.py` - MCP server for Claude Code integration

## Environment Variables

Required in `.env`:
```
SECRET_KEY=<django-secret>
DEBUG=TRUE/FALSE
GEMINI_API_KEY=<key>  # Server-side fallback for Gemini
```

Optional:
```
DATABASE_URL=postgres://...  # Falls back to SQLite
NASA_API_KEY=<key>
SERVE_MEDIA=TRUE  # For PaaS deployments
RUN_AUDIT_SCHEDULER=FALSE
```

## Database Notes

- Development: SQLite (`db.sqlite3`)
- Production: PostgreSQL supported via `DATABASE_URL`
- PostgreSQL returns `memoryview` for BinaryFields - convert to `bytes()` before Fernet decryption

## Testing

Tests are in `core/tests.py` and `core/tests/`. CI runs on GitHub Actions (Windows, Python 3.10/3.13).
