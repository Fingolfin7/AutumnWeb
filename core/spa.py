"""Serve the React app (frontend/) from Django.

Django always renders the HTML document so that cookies, CSRF, auth redirects
and the workspace backdrop work exactly as on the server-rendered pages. The
document carries a JSON bootstrap blob so the app's first paint needs no
request of its own.

Production loads the hashed bundle named in Vite's manifest
(core/static/app/manifest.json, written by `npm run build`). Development sets
VITE_DEV_SERVER (e.g. http://localhost:5173) to load modules from Vite with
hot reload instead.
"""
import json
import logging
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import staticfiles_storage
from django.http import Http404
from django.middleware.csrf import get_token
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.cache import patch_cache_control
from django.views.decorators.http import require_GET

from core.models import Context
from core.utils import get_active_context

logger = logging.getLogger(__name__)

ENTRY = "src/main.tsx"
MANIFEST = "app/manifest.json"


def _read_manifest():
    path = finders.find(MANIFEST)
    if not path and settings.STATIC_ROOT:
        candidate = Path(settings.STATIC_ROOT) / MANIFEST
        path = str(candidate) if candidate.exists() else None
    if not path:
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def _cached_manifest():
    return _read_manifest()


def manifest():
    # Re-read on every request in DEBUG so a rebuild shows up without a restart.
    return _read_manifest() if settings.DEBUG else _cached_manifest()


def asset_tags():
    """Return {"scripts": [...], "styles": [...], "preloads": [...], "dev": bool}."""
    dev_server = getattr(settings, "VITE_DEV_SERVER", "")
    if dev_server:
        base = dev_server.rstrip("/")
        return {"dev": True, "dev_server": base, "scripts": [f"{base}/{ENTRY}"], "styles": [], "preloads": []}

    data = manifest()
    if not data or ENTRY not in data:
        return None
    entry = data[ENTRY]
    styles = list(entry.get("css", []))
    preloads = []
    seen = set()

    def walk(key):
        for imported in data.get(key, {}).get("imports", []):
            if imported in seen:
                continue
            seen.add(imported)
            chunk = data.get(imported, {})
            if chunk.get("file"):
                preloads.append(chunk["file"])
            styles.extend(chunk.get("css", []))
            walk(imported)

    walk(ENTRY)

    def url(file):
        return staticfiles_storage.url(f"app/{file}")

    return {
        "dev": False,
        "scripts": [url(entry["file"])],
        "styles": [url(file) for file in dict.fromkeys(styles)],
        "preloads": [url(file) for file in preloads],
    }


MESSAGE_KINDS = {
    messages.SUCCESS: "success",
    messages.WARNING: "warning",
    messages.ERROR: "error",
}


def bootstrap_payload(request):
    """Data the app needs before its first render.

    Kept deliberately small: everything else is fetched through /api/v2/.
    """
    user = request.user
    profile = user.profile
    default_chart_start_date, default_chart_end_date = (
        profile.default_filter_date_range()
    )
    active_context, _mode = get_active_context(request)
    contexts = list(
        Context.objects.filter(user=user).order_by("name").values("id", "name")
    )
    return {
        "user": {"id": user.id, "username": user.username, "email": user.email},
        "profile": {
            "avatar_url": profile.image_url,
            "timezone": profile.timezone,
            "background_dimming": profile.background_dimming,
            "insights_access_enabled": profile.insights_access_enabled,
            "ai_features_enabled": profile.ai_features_enabled,
            "default_chart_project_count": profile.default_chart_project_count,
            "default_chart_start_date": default_chart_start_date.isoformat(),
            "default_chart_end_date": default_chart_end_date.isoformat(),
            "openai_key_configured": bool(profile.openai_api_key_enc),
        },
        "contexts": contexts,
        "active_context_id": active_context.id if active_context else None,
        "csrf_token": get_token(request),
        "static": {
            "leaf": staticfiles_storage.url("core/images/new_autumn_leaf_transparent_slanted.png"),
            "insights_empty": staticfiles_storage.url(
                "core/images/reddit_such_empty_transparent.png"
            ),
        },
        "push": {"vapid_public_key": getattr(settings, "PUSH_VAPID_PUBLIC_KEY", "") or ""},
        "debug": settings.DEBUG,
        # Flash messages from a redirect into the app (e.g. back from an
        # OAuth connect); the app shows them as toasts. Reading consumes them.
        "messages": [
            {"kind": MESSAGE_KINDS.get(message.level, "info"), "text": str(message)}
            for message in messages.get_messages(request)
        ],
    }


@require_GET
@login_required
def spa(request, *args, **kwargs):
    assets = asset_tags()
    if assets is None:
        logger.error("React bundle missing: run `npm run build` in frontend/ (no %s).", MANIFEST)
        raise Http404("The web app has not been built.")
    response = render(
        request,
        "core/spa.html",
        {
            "assets": assets,
            "bootstrap": bootstrap_payload(request),
        },
    )
    # The service worker keeps this page as the offline app shell
    # (core/static/core/pwa/service-worker.js); the browser cache must not.
    response["X-Autumn-Shell"] = "1"
    patch_cache_control(response, no_cache=True, private=True)
    return response


@require_GET
@login_required
def reminder_action(request, reminder_id, action):
    """The old per-reminder pages, still the target of a scheduled reminder's
    Snooze notification action: open that dialog on the Notifications page."""
    return redirect(f"{reverse('notifications')}?{action}={reminder_id}")
