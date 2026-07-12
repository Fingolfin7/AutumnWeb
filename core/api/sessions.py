from __future__ import annotations
from datetime import timedelta
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from core.models import Projects, SubProjects, Sessions
from core.session_ledger import (
    delete_session as ledger_delete_session,
    mutate_session as ledger_mutate_session,
)
from core.serializers import (
    SessionSerializer,
)
from core.utils import (
    parse_date_or_datetime,
    filter_sessions_by_params,
    filter_by_active_context,
    stop_expired_timers,
)
from django.db import transaction
from core.api.helpers import _apply_exclude_filters, _apply_tag_filters, _bool, _coerce_list, _compact, _err, _json_ok, _now, _serialize_session
from core.api.timers import timer_restart, timer_start, timer_stop, track_session


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def search_sessions(request):
    """
    Search sessions by any of: project, subproject, start_date, end_date,
    note_snippet. At least one of those must be provided.
    Optional:
      - active=true|false (default false -> saved sessions)
      - order (default: '-end_time' for saved, '-start_time' for active)
      - limit, offset
      - compact=true|false (default true)
    Returns compact by default: {"count", "sessions":[{id,p,subs,start,end,dur}]}
    """
    compact = _compact(request)
    qp = request.query_params

    # Require at least one primary search field
    if not any(
        qp.get(k)
        for k in (
            "project",
            "project_name",
            "subproject",
            "start_date",
            "end_date",
            "note_snippet",
        )
    ):
        return _err(
            "Provide at least one of: project|subproject|start_date|"
            "end_date|note_snippet"
        )

    active = _bool(qp.get("active"), False)
    order = qp.get("order") or ("-start_time" if active else "-end_time")
    limit = qp.get("limit")
    offset = qp.get("offset")

    # Normalize alias: project -> project_name for the filter helper
    qp2 = qp.copy()
    if qp2.get("project") and not qp2.get("project_name"):
        qp2["project_name"] = qp2["project"]

    sessions = Sessions.objects.filter(user=request.user)
    sessions = (
        sessions.filter(is_active=True) if active else sessions.filter(is_active=False)
    )

    # context filter (consistent with other endpoints)
    sessions = filter_by_active_context(
        sessions, request, override_context_id=qp.get("context")
    )
    # tag filter
    sessions = _apply_tag_filters(qp, sessions, kind="sessions", user=request.user)

    # Shim request so filter_sessions_by_params sees the normalized params
    shim = type("Req", (), {"query_params": qp2, "GET": qp2})()
    sessions = filter_sessions_by_params(shim, sessions)

    try:
        sessions = sessions.order_by(order)
    except Exception:
        sessions = sessions.order_by("-end_time")

    # lightweight paging
    try:
        if offset is not None:
            sessions = sessions[int(offset) :]
        if limit is not None:
            sessions = sessions[: int(limit)]
    except Exception:
        pass

    if compact:
        payload = [
            {
                "id": s.id,
                "p": s.project.name,
                "pid": s.project.id,
                "subs": [sp.name for sp in s.subprojects.all()],
                "start": s.start_time.isoformat(),
                "end": s.end_time.isoformat() if s.end_time else None,
                "dur": s.duration,  # minutes
                "crosses_dst_transition": s.crosses_dst_transition,
            }
            for s in sessions
        ]
        return Response({"count": len(payload), "sessions": payload})
    else:
        payload = [
            {
                "id": s.id,
                "project": s.project.name,
                "project_id": s.project.id,
                "subprojects": [sp.name for sp in s.subprojects.all()],
                "start_time": s.start_time.isoformat(),
                "end_time": s.end_time.isoformat() if s.end_time else None,
                "duration_minutes": s.duration,
                "note": s.note or "",
                "is_active": s.is_active,
                "crosses_dst_transition": s.crosses_dst_transition,
            }
            for s in sessions
        ]
        return Response({"count": len(payload), "sessions": payload})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def log_activity(request):
    """
    Show activity logs. Supports:
      - period=week|month|day|all
      - start_date?, end_date?
      - project or project_name
      - subproject
      - note_snippet
      - context?
      - tags?
      - compact?
    Defaults to period=week if no start/end/period filters provided by client.
    """
    compact = _compact(request)
    qp = request.query_params
    period = (qp.get("period") or "").lower()

    sessions = Sessions.objects.filter(is_active=False, user=request.user)
    sessions = filter_by_active_context(
        sessions, request, override_context_id=qp.get("context")
    )
    sessions = _apply_tag_filters(qp, sessions, kind="sessions", user=request.user)

    # Default period window if no explicit start/end
    if period in ("day", "week", "month") and not (
        qp.get("start_date") or qp.get("end_date")
    ):
        now = timezone.localtime(_now())
        if period == "day":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            # Trailing 7-day window (inclusive) rather than "since Monday"
            start = (now - timedelta(days=7)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        else:
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        sessions = sessions.filter(end_time__gte=start)

    # Normalize alias: project -> project_name for the filter helper
    qp2 = qp.copy()
    if qp2.get("project") and not qp2.get("project_name"):
        qp2["project_name"] = qp2["project"]

    shim = type("Req", (), {"query_params": qp2, "GET": qp2})()
    sessions = filter_sessions_by_params(shim, sessions).order_by("-end_time")

    if compact:
        logs = [
            {
                "id": s.id,
                "p": s.project.name,
                "pid": s.project.id,
                "subs": [sp.name for sp in s.subprojects.all()],
                "start": s.start_time.isoformat(),
                "end": s.end_time.isoformat() if s.end_time else None,
                "dur": s.duration,  # minutes
                "crosses_dst_transition": s.crosses_dst_transition,
            }
            for s in sessions
        ]
    else:
        logs = [
            {
                "id": s.id,
                "project": s.project.name,
                "project_id": s.project.id,
                "subprojects": [sp.name for sp in s.subprojects.all()],
                "start_time": s.start_time.isoformat(),
                "end_time": s.end_time.isoformat() if s.end_time else None,
                "duration_minutes": s.duration,
                "note": s.note or "",
                "crosses_dst_transition": s.crosses_dst_transition,
            }
            for s in sessions
        ]
    return Response({"count": len(logs), "logs": logs})


# Back-compat shims (mapping to new compact endpoints)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def start_session(request):
    # delegate to timer_start
    return timer_start(request)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def restart_session(request):
    # delegate to timer_restart
    return timer_restart(request)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def end_session(request):
    # delegate to timer_stop
    return timer_stop(request)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def log_session(request):
    # delegate to track_session
    return track_session(request)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_session(request, session_id):
    try:
        session_id = int(session_id)
    except (TypeError, ValueError):
        return _err("Invalid session id", status.HTTP_400_BAD_REQUEST)
    if session_id <= 0:
        return _err("Session not found", status.HTTP_404_NOT_FOUND)

    sess = Sessions.objects.filter(pk=session_id, user=request.user).first()
    if not sess:
        return _err("Session not found", status.HTTP_404_NOT_FOUND)
    ledger_delete_session(sess.pk, user=request.user)
    return Response(status=204)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def edit_session(request, session_id):
    """
    Edit an existing completed session in place, preserving its ID.

    JSON body (all optional, only provided fields are updated):
      - project: str (project name to reassign session to)
      - subprojects: [str] (list of subproject names)
      - start: str (ISO timestamp)
      - end: str (ISO timestamp)
      - note: str

    Query params:
      - compact: true/false (default true)

    Returns the updated session object with the same ID.
    """
    compact = _compact(request)
    try:
        session_id = int(session_id)
    except (TypeError, ValueError):
        return _err("Invalid session id", status.HTTP_400_BAD_REQUEST)
    if session_id <= 0:
        return _err("Session not found", status.HTTP_404_NOT_FOUND)

    current_session = (
        Sessions.objects.select_for_update()
        .filter(pk=session_id, user=request.user)
        .first()
    )
    if not current_session:
        return _err("Session not found", status.HTTP_404_NOT_FOUND)

    # Only allow editing completed sessions
    if current_session.is_active:
        return _err("Cannot edit active sessions. Stop the timer first.")

    # Collect current values as defaults
    project = current_session.project
    start_time = current_session.start_time
    end_time = current_session.end_time
    note = current_session.note
    current_subs = list(current_session.subprojects.all())

    # Apply updates from request body
    data = request.data

    # Update project if provided
    if "project" in data and data["project"]:
        project = Projects.objects.filter(
            name=data["project"], user=request.user
        ).first()
        if not project:
            return _err("Project not found", status.HTTP_404_NOT_FOUND)

    # Update start/end times if provided
    if "start" in data and data["start"]:
        try:
            start_time = parse_date_or_datetime(data["start"])
            if timezone.is_naive(start_time):
                start_time = timezone.make_aware(start_time)
        except Exception as e:
            return _err(f"Invalid start time: {e}")

    if "end" in data and data["end"]:
        try:
            end_time = parse_date_or_datetime(data["end"])
            if timezone.is_naive(end_time):
                end_time = timezone.make_aware(end_time)
        except Exception as e:
            return _err(f"Invalid end time: {e}")

    # Validate times
    if end_time and start_time and end_time < start_time:
        return _err("End time cannot be earlier than start time")

    # Update note if provided (allow empty string to clear note)
    if "note" in data:
        note = data["note"] if data["note"] else None

    # Resolve subprojects if provided
    sub_qs = None
    if "subprojects" in data:
        subs = _coerce_list(data.get("subprojects"))
        if subs:
            sub_qs = SubProjects.objects.filter(
                parent_project=project, user=request.user, name__in=subs
            )
            if sub_qs.count() != len(set([s.lower() for s in subs])):
                existing = set(sp.name.lower() for sp in sub_qs)
                missing = [s for s in subs if s.lower() not in existing]
                return _err(f"Unknown subprojects: {', '.join(missing)}")
        else:
            sub_qs = SubProjects.objects.none()

    # Resolve the final subproject set before changing the existing row.
    if sub_qs is not None:
        final_subprojects = list(sub_qs)
    else:
        # Keep existing subprojects (filtering to those valid for the new project)
        final_subprojects = [
            sp for sp in current_subs if sp.parent_project_id == project.id
        ]

    current_session = ledger_mutate_session(
        current_session.pk,
        user=request.user,
        project=project,
        subprojects=final_subprojects,
        start_time=start_time,
        end_time=end_time,
        note=note,
        is_active=False,
    )

    return Response(
        _json_ok({"session": _serialize_session(current_session, compact)}, compact),
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_sessions(request):
    sessions = Sessions.objects.filter(is_active=False, user=request.user)
    sessions = filter_by_active_context(
        sessions, request, override_context_id=request.query_params.get("context")
    )
    sessions = _apply_tag_filters(
        request.query_params, sessions, kind="sessions", user=request.user
    )
    sessions = _apply_exclude_filters(
        request.query_params, sessions, kind="sessions", user=request.user
    )
    sessions = filter_sessions_by_params(request, sessions)
    serializer = SessionSerializer(sessions, many=True)
    # to_representation already compacts project/subprojects as names
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_active_sessions(request):
    stop_expired_timers(request.user)
    sessions = Sessions.objects.filter(is_active=True, user=request.user)
    sessions = filter_by_active_context(
        sessions, request, override_context_id=request.query_params.get("context")
    )
    serializer = SessionSerializer(sessions, many=True)
    return Response(serializer.data)
