from __future__ import annotations
from datetime import timedelta
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from core.models import Projects, SubProjects, Sessions
from core.session_ledger import (
    create_session as ledger_create_session,
    delete_session as ledger_delete_session,
    mutate_session as ledger_mutate_session,
)
from core.utils import (
    parse_stop_after_duration,
    stop_expired_timers,
)
from core.api.helpers import _coerce_list, _compact, _err, _get_active_sessions, _json_ok, _now, _parse_client_instant, _parse_track_times, _pick_target_session, _serialize_session


# -----------------------
# New compact API
# -----------------------


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def timer_start(request):
    """
    Start a new timer.
    JSON: { "project": str, "subprojects": [str]|"a,b", "note": str?, "start": iso? }
    """
    compact = _compact(request)
    project_name = request.data.get("project")
    if not project_name:
        return _err("Missing 'project'")

    project = Projects.objects.filter(name=project_name, user=request.user).first()
    if not project:
        return _err("Project not found", status.HTTP_404_NOT_FOUND)

    stop_after_value = request.data.get("stop_after")
    if stop_after_value is None:
        stop_after_value = request.data.get("stop_after_minutes")

    try:
        stop_after = parse_stop_after_duration(stop_after_value)
    except ValueError as exc:
        return _err(str(exc))

    subs = _coerce_list(request.data.get("subprojects"))
    note = request.data.get("note", "").strip()

    # Resolve subprojects (must exist)
    sub_qs = SubProjects.objects.filter(
        parent_project=project, user=request.user, name__in=subs
    )
    if subs and sub_qs.count() != len(set([s.lower() for s in subs])):
        # find missing
        existing = set(sp.name.lower() for sp in sub_qs)
        missing = [s for s in subs if s.lower() not in existing]
        return _err(f"Unknown subprojects: {', '.join(missing)}")

    start_time = _now()
    if request.data.get("start"):
        try:
            start_time = _parse_client_instant(request.data["start"], "start")
        except ValueError as exc:
            return _err(str(exc))

    sess = ledger_create_session(
        user=request.user,
        project=project,
        start_time=start_time,
        auto_stop_at=start_time + stop_after if stop_after else None,
        is_active=True,
        note=note or None,
        subprojects=list(sub_qs),
    )

    return Response(
        _json_ok({"session": _serialize_session(sess, compact)}, compact),
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def timer_stop(request):
    """
    Stop the current timer (or a specific one).
    JSON: { "session_id": int?, "project": str?, "note": str?, "end": iso? }
    """
    compact = _compact(request)
    stop_expired_timers(request.user)
    sess = _pick_target_session(
        request.user,
        session_id=request.data.get("session_id"),
        project_name=request.data.get("project"),
    )
    if not sess:
        return _err("No active timer found", status.HTTP_404_NOT_FOUND)
    if not sess.is_active:
        return _err("Session not active", status.HTTP_400_BAD_REQUEST)

    end_time = _now()
    if request.data.get("end"):
        try:
            end_time = _parse_client_instant(request.data["end"], "end")
        except ValueError as exc:
            return _err(str(exc))
        if end_time < sess.start_time:
            return _err("'end' is before the session start")

    note = sess.note
    if "note" in request.data and request.data["note"] is not None:
        note = str(request.data["note"])
    sess = ledger_mutate_session(
        sess.pk,
        user=request.user,
        end_time=end_time,
        is_active=False,
        auto_stop_at=None,
        note=note,
    )

    return Response(
        _json_ok(
            {
                "session": _serialize_session(sess, compact),
                "duration": sess.duration,
            },
            compact,
        ),
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def timer_status(request):
    """
    Show status of current timer(s).
    Query: session_id?, project?
    """
    stop_expired_timers(request.user)
    compact = _compact(request)
    qp = request.query_params
    session_id = qp.get("session_id")
    project = qp.get("project")
    if session_id:
        try:
            sess = Sessions.objects.get(pk=int(session_id), user=request.user)
            if not sess.is_active:
                return _err("Session not active", status.HTTP_400_BAD_REQUEST)
            return Response(
                _json_ok({"session": _serialize_session(sess, compact)}, compact)
            )
        except Sessions.DoesNotExist:
            return _err("Session not found", status.HTTP_404_NOT_FOUND)

    actives = _get_active_sessions(request.user, project)
    if not actives.exists():
        return Response(_json_ok({"active": 0}, compact))

    payload = (
        [_serialize_session(s, compact) for s in actives]
        if not compact
        else [_serialize_session(s, True) for s in actives]
    )
    return Response(_json_ok({"active": len(payload), "sessions": payload}, compact))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def timer_restart(request):
    """
    Restart current timer (or a specific one): set start_time=now, active=True.
    JSON: { "session_id": int?, "project": str? }
    """
    compact = _compact(request)
    stop_expired_timers(request.user)
    sess = _pick_target_session(
        request.user,
        session_id=request.data.get("session_id"),
        project_name=request.data.get("project"),
    )
    if not sess:
        return _err("No active timer found", status.HTTP_404_NOT_FOUND)

    restart_time = _now()
    auto_stop_duration = None
    if sess.auto_stop_at and sess.start_time and sess.auto_stop_at > sess.start_time:
        auto_stop_duration = sess.auto_stop_at - sess.start_time

    sess = ledger_mutate_session(
        sess.pk,
        user=request.user,
        start_time=restart_time,
        is_active=True,
        end_time=None,
        auto_stop_at=(
            restart_time + auto_stop_duration if auto_stop_duration else None
        ),
    )
    return Response(_json_ok({"session": _serialize_session(sess, compact)}, compact))


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def timer_delete(request):
    """
    Remove a timer without saving a session.
    JSON: { "session_id": int? } or query param session_id
    If not provided, deletes most-recent active session.
    """
    compact = _compact(request)
    session_id = request.data.get("session_id") or request.query_params.get(
        "session_id"
    )
    sess = _pick_target_session(request.user, session_id=session_id)
    if not sess:
        return _err("No active timer found", status.HTTP_404_NOT_FOUND)

    sess_id = sess.id
    ledger_delete_session(sess.pk, user=request.user)
    return Response(_json_ok({"deleted": sess_id}, compact), status=200)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def track_session(request):
    """
    Track a project for a given time period (saved completed session).
    JSON:
      {
        "project": str,
        "subprojects": [str]|"a,b",
        "start": str(iso)?,
        "end": str(iso)?,
        "date": "%m-%d-%Y"?,
        "start_time": "%H:%M:%S"?,
        "end_time": "%H:%M:%S"?,
        "note": str?
      }
    """
    compact = _compact(request)
    project_name = request.data.get("project")
    if not project_name:
        return _err("Missing 'project'")

    project = Projects.objects.filter(name=project_name, user=request.user).first()
    if not project:
        return _err("Project not found", status.HTTP_404_NOT_FOUND)

    try:
        start_time, end_time = _parse_track_times(request.data)
    except ValueError as e:
        return _err(str(e))

    if end_time < start_time:
        # crossed midnight
        start_time -= timedelta(days=1)

    subs = _coerce_list(request.data.get("subprojects"))
    sub_qs = SubProjects.objects.filter(
        parent_project=project, user=request.user, name__in=subs
    )
    if subs and sub_qs.count() != len(set([s.lower() for s in subs])):
        existing = set(sp.name.lower() for sp in sub_qs)
        missing = [s for s in subs if s.lower() not in existing]
        return _err(f"Unknown subprojects: {', '.join(missing)}")

    note = request.data.get("note", "").strip()
    sess = ledger_create_session(
        user=request.user,
        project=project,
        start_time=start_time,
        end_time=end_time,
        is_active=False,
        note=note or None,
        subprojects=list(sub_qs),
    )

    return Response(
        _json_ok({"session": _serialize_session(sess, compact)}, compact),
        status=status.HTTP_201_CREATED,
    )
