"""Request/queryset helpers that outlived the v1 API.

These were part of core/api/helpers.py; the v1 API package was removed in
S12, but the v2 API and tests still use this handful of utilities.
"""

from __future__ import annotations
from datetime import date, datetime

from core.models import Projects, Sessions, Tag
from core.utils import stop_expired_timers


def _coerce_list(val):
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        if not val:
            return []
        return [v.strip() for v in val.split(",") if v.strip()]
    return list(val)


def _iso_value(value):
    """Convert dates in commitment-domain results to JSON-safe ISO strings."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _iso_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_iso_value(item) for item in value]
    return value


def _get_active_sessions(user, project_name=None):
    stop_expired_timers(user)
    qs = Sessions.objects.filter(end_time__isnull=True, user=user).order_by("-start_time")
    if project_name:
        qs = qs.filter(project__name__iexact=project_name)
    return qs


def _apply_tag_filters(qp, qs, *, kind: str, user=None):
    """Apply tag filtering from query params.

    Query param: tags="a,b" or tags=["a","b"]

    kind:
      - "projects": expects Projects queryset
      - "sessions": expects Sessions queryset (filters via project__tags)
    """
    try:
        tags = _coerce_list(qp.get("tags"))
    except Exception:
        tags = []

    if not tags:
        return qs

    # Ensure tags belong to the same user (avoid leaking tag names across users)
    # This also normalizes case by using iexact matches if needed.
    if user is not None:
        tags = list(
            Tag.objects.filter(user=user, name__in=tags).values_list("name", flat=True)
        )

    if not tags:
        return qs

    if kind == "projects":
        return qs.filter(tags__name__in=tags).distinct()
    if kind == "sessions":
        return qs.filter(project__tags__name__in=tags).distinct()

    return qs


def _apply_exclude_filters(qp, qs, *, kind: str, user=None):
    """Exclude projects by name from query params.

    Query param: exclude="ProjectA,ProjectB" or exclude=["ProjectA","ProjectB"]

    kind:
      - "projects": expects Projects queryset
      - "sessions": expects Sessions queryset (excludes via project__name)
    """
    try:
        names = _coerce_list(qp.get("exclude"))
    except Exception:
        names = []

    if not names:
        return qs

    if user is not None:
        names = list(
            Projects.objects.filter(user=user, name__in=names).values_list("name", flat=True)
        )

    if not names:
        return qs

    if kind == "projects":
        return qs.exclude(name__in=names)
    if kind == "sessions":
        return qs.exclude(project__name__in=names)

    return qs
