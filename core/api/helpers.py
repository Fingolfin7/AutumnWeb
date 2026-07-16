from __future__ import annotations
from datetime import date, datetime
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.response import Response
from rest_framework import status
from core.models import Projects, Sessions, Tag, Context
from core.utils import (
    parse_date_or_datetime,
    stop_expired_timers,
)


# -----------------------
# Helpers
# -----------------------


def _now() -> datetime:
    return timezone.now()


def _bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("1", "true", "yes", "y", "on")


def _compact(request) -> bool:
    qp = getattr(request, "query_params", request.GET)
    return _bool(qp.get("compact"), True)


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


def _json_ok(extra=None, compact=True):
    base = {"ok": True} if compact else {"ok": True, "message": "success"}
    return {**base, **(extra or {})}


def _err(msg, code=status.HTTP_400_BAD_REQUEST):
    return Response({"ok": False, "error": msg}, status=code)


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
    qs = Sessions.objects.filter(is_active=True, user=user).order_by("-start_time")
    if project_name:
        qs = qs.filter(project__name__iexact=project_name)
    return qs


def _pick_target_session(user, session_id=None, project_name=None):
    if session_id:
        return get_object_or_404(Sessions, pk=session_id, user=user)
    qs = _get_active_sessions(user, project_name)
    return qs.first()


def _serialize_session(sess: Sessions, compact=True):
    elapsed = sess.duration
    if compact:
        d = {
            "id": sess.id,
            "p": sess.project.name,
            "pid": sess.project.id,
            "subs": [sp.name for sp in sess.subprojects.all()],
            "start": sess.start_time.isoformat(),
            "end": sess.end_time.isoformat() if sess.end_time else None,
            "stop_at": sess.auto_stop_at.isoformat() if sess.auto_stop_at else None,
            "active": sess.is_active,
            "elapsed": elapsed,
            "crosses_dst_transition": sess.crosses_dst_transition,
        }
        if sess.note:
            d["note"] = sess.note
        return d
    return {
        "id": sess.id,
        "project": sess.project.name,
        "project_id": sess.project.id,
        "subprojects": [sp.name for sp in sess.subprojects.all()],
        "start_time": sess.start_time.isoformat(),
        "end_time": sess.end_time.isoformat() if sess.end_time else None,
        "auto_stop_at": sess.auto_stop_at.isoformat() if sess.auto_stop_at else None,
        "is_active": sess.is_active,
        "elapsed_minutes": elapsed,
        "note": sess.note or "",
        "crosses_dst_transition": sess.crosses_dst_transition,
    }


def _serialize_project_grouped(projects, compact=True):
    # Be tolerant of unexpected/legacy status values.
    # Older data can include 'archived' (and potentially others), so don't assume
    # only active/paused/complete exists.
    groups = {"active": [], "paused": [], "complete": [], "archived": []}
    for p in projects:
        key = getattr(p, "status", None) or "active"
        if key not in groups:
            groups[key] = []

        if compact:
            groups[key].append(p.name)
        else:
            # Calculate session stats
            sessions = p.sessions.filter(is_active=False)
            session_count = sessions.count()
            avg_session = (p.total_time / session_count) if session_count > 0 else 0

            groups[key].append(
                {
                    "id": p.id,
                    "name": p.name,
                    "status": p.status,
                    "total_time": p.total_time,
                    "session_count": session_count,
                    "avg_session_duration": round(avg_session, 1),
                    "start_date": p.start_date.isoformat(),
                    "last_updated": p.last_updated.isoformat(),
                    "description": p.description or "",
                    "context": p.context.name if p.context else None,
                    "tags": [t.name for t in p.tags.all()],
                }
            )

    summary = {
        "active": len(groups.get("active", [])),
        "paused": len(groups.get("paused", [])),
        "complete": len(groups.get("complete", [])),
        "archived": len(groups.get("archived", [])),
        "total": len(projects),
    }
    return {"summary": summary, "projects": groups}


def _parse_client_instant(value, field, *, max_future_minutes=5):
    """Parse a client-supplied instant for timer start/stop.

    Clients on sleeping hosts send the instant the user ran the command so a
    wake delay never skews recorded times. Rejects instants more than
    max_future_minutes ahead of server time (clock-skew guard).
    """
    from datetime import timedelta

    try:
        instant = parse_date_or_datetime(str(value))
    except (ValueError, TypeError):
        raise ValueError(f"Invalid '{field}' timestamp: {value!r}")
    if instant is None:
        raise ValueError(f"Invalid '{field}' timestamp: {value!r}")
    if timezone.is_naive(instant):
        instant = timezone.make_aware(instant)
    if instant > timezone.now() + timedelta(minutes=max_future_minutes):
        raise ValueError(f"'{field}' is in the future")
    return instant


def _parse_track_times(data):
    # Accept either ISO strings:
    #   start, end
    # Or legacy: date + start_time, end_time in %m-%d-%Y / %H:%M:%S formats.
    if data.get("start") and data.get("end"):
        start = parse_date_or_datetime(data["start"])
        end = parse_date_or_datetime(data["end"])
        if timezone.is_naive(start):
            start = timezone.make_aware(start)
        if timezone.is_naive(end):
            end = timezone.make_aware(end)
        return start, end

    date = data.get("date")
    st = data.get("start_time")
    et = data.get("end_time")
    if not (date and st and et):
        raise ValueError(
            "Provide either 'start' and 'end' (ISO or known fmt) or "
            "'date', 'start_time', 'end_time'."
        )

    start = timezone.make_aware(datetime.strptime(f"{date} {st}", "%m-%d-%Y %H:%M:%S"))
    end = timezone.make_aware(datetime.strptime(f"{date} {et}", "%m-%d-%Y %H:%M:%S"))
    return start, end


# -----------------------
# Existing endpoints (moved here, small fixes), kept for compatibility
# -----------------------


def _clean_required_name(value, label):
    if not isinstance(value, str):
        raise ValueError(f"'{label}' must be a string.")
    value = value.strip()
    if not value:
        raise ValueError(f"Missing '{label}'.")
    if len(value) > 100:
        raise ValueError(f"'{label}' must be 100 characters or fewer.")
    return value


def _clean_optional_text(value, label, *, allow_null=False, max_length=None):
    if value is None and allow_null:
        return None
    if not isinstance(value, str):
        raise ValueError(f"'{label}' must be a string.")
    value = value.strip()
    if max_length is not None and len(value) > max_length:
        raise ValueError(f"'{label}' must be {max_length} characters or fewer.")
    return value


def _resolve_context_name(user, value):
    name = _clean_required_name(value, "context")
    context = Context.objects.filter(user=user, name__iexact=name).first()
    if context:
        return context
    available = list(
        Context.objects.filter(user=user).order_by("name").values_list("name", flat=True)
    )
    available_names = ", ".join(available) if available else "(none)"
    raise ValueError(
        f"Unknown context '{name}'. Available contexts: {available_names}."
    )


def _resolve_tag_names(user, value):
    if not isinstance(value, list):
        raise ValueError("'tags' must be a list of strings.")

    names = [_clean_required_name(raw_name, "tag") for raw_name in _coerce_list(value)]
    tags = []
    for name in names:
        tag = Tag.objects.filter(user=user, name__iexact=name).first()
        if not tag:
            tag = Tag.objects.create(user=user, name=name)
        if tag not in tags:
            tags.append(tag)
    return tags


def _serialize_project_metadata(project, compact):
    context_name = project.context.name if project.context else None
    tag_names = [tag.name for tag in project.tags.all()]
    if compact:
        return {
            "p": project.name,
            "desc": project.description,
            "status": project.status,
            "ctx": context_name,
            "tags": tag_names,
        }
    return {
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "context": context_name,
        "tags": tag_names,
    }


def _serialize_context_for_api(context, user, compact):
    if compact:
        return {"id": context.id, "name": context.name}

    project_count = context.projects.count()
    sessions = Sessions.objects.filter(
        user=user,
        project__context=context,
        is_active=False,
    )
    session_count = sessions.count()
    total_minutes = sum(session.duration or 0 for session in sessions)
    return {
        "id": context.id,
        "name": context.name,
        "description": context.description or "",
        "project_count": project_count,
        "session_count": session_count,
        "total_minutes": round(total_minutes, 2),
        "avg_session_minutes": (
            round(total_minutes / session_count, 2) if session_count > 0 else 0.0
        ),
    }


def _serialize_tag_for_api(tag, user, compact):
    if compact:
        return {"id": tag.id, "name": tag.name}

    project_count = tag.projects.filter(user=user).count()
    sessions = Sessions.objects.filter(
        user=user,
        project__tags=tag,
        is_active=False,
    )
    session_count = sessions.count()
    total_minutes = sum(session.duration or 0 for session in sessions)
    return {
        "id": tag.id,
        "name": tag.name,
        "color": tag.color or "",
        "project_count": project_count,
        "session_count": session_count,
        "total_minutes": round(total_minutes, 2),
        "avg_session_minutes": (
            round(total_minutes / session_count, 2) if session_count > 0 else 0.0
        ),
    }


# Needed by list_projects
def in_window(data, start=None, end=None):
    from core.utils import in_window as _inw

    return _inw(data, start, end)


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
