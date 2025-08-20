# core/api.py
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from collections import defaultdict

from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Min, Max

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from .models import Projects, SubProjects, Sessions, status_choices
from .serializers import (
  ProjectSerializer,
  SubProjectSerializer,
  SessionSerializer,
)
from .utils import (
  parse_date_or_datetime,
  filter_sessions_by_params,
  tally_project_durations,
  session_exists,
  sessions_get_earliest_latest,
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

def _get_active_sessions(user, project_name=None):
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
      "subs": [sp.name for sp in sess.subprojects.all()],
      "start": sess.start_time.isoformat(),
      "end": sess.end_time.isoformat() if sess.end_time else None,
      "active": sess.is_active,
      "elapsed": elapsed,
    }
    if sess.note:
      d["note"] = sess.note
    return d
  return {
    "id": sess.id,
    "project": sess.project.name,
    "subprojects": [sp.name for sp in sess.subprojects.all()],
    "start_time": sess.start_time.isoformat(),
    "end_time": sess.end_time.isoformat() if sess.end_time else None,
    "is_active": sess.is_active,
    "elapsed_minutes": elapsed,
    "note": sess.note or "",
  }

def _serialize_project_grouped(projects, compact=True):
  groups = {"active": [], "paused": [], "complete": []}
  for p in projects:
    if compact:
      groups[p.status].append(p.name)
    else:
      groups[p.status].append(
        {
          "id": p.id,
          "name": p.name,
          "status": p.status,
          "total_time": p.total_time,
          "start_date": p.start_date.isoformat(),
          "last_updated": p.last_updated.isoformat(),
          "description": p.description or "",
        }
      )
  summary = {
    "active": len(groups["active"]),
    "paused": len(groups["paused"]),
    "complete": len(groups["complete"]),
    "total": len(projects),
  }
  return {"summary": summary, "projects": groups}

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

  start = timezone.make_aware(
    datetime.strptime(f"{date} {st}", "%m-%d-%Y %H:%M:%S")
  )
  end = timezone.make_aware(
    datetime.strptime(f"{date} {et}", "%m-%d-%Y %H:%M:%S")
  )
  return start, end


# -----------------------
# New compact API
# -----------------------

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def timer_start(request):
  """
  Start a new timer.
  JSON: { "project": str, "subprojects": [str]|"a,b", "note": str? }
  """
  compact = _compact(request)
  project_name = request.data.get("project")
  if not project_name:
    return _err("Missing 'project'")

  project = Projects.objects.filter(
    name=project_name, user=request.user
  ).first()
  if not project:
    return _err("Project not found", status.HTTP_404_NOT_FOUND)

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

  sess = Sessions.objects.create(
    user=request.user,
    project=project,
    start_time=_now(),
    is_active=True,
    note=note or None,
  )
  if sub_qs.exists():
    sess.subprojects.add(*list(sub_qs))

  sess.full_clean()
  sess.save()

  return Response(
    _json_ok({"session": _serialize_session(sess, compact)}, compact),
    status=status.HTTP_201_CREATED,
  )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def timer_stop(request):
  """
  Stop the current timer (or a specific one).
  JSON: { "session_id": int?, "project": str?, "note": str? }
  """
  compact = _compact(request)
  sess = _pick_target_session(
    request.user,
    session_id=request.data.get("session_id"),
    project_name=request.data.get("project"),
  )
  if not sess:
    return _err("No active timer found", status.HTTP_404_NOT_FOUND)

  sess.end_time = _now()
  sess.is_active = False
  if "note" in request.data and request.data["note"] is not None:
    sess.note = str(request.data["note"])
  sess.full_clean()
  sess.save()

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
    else [
      _serialize_session(s, True) for s in actives
    ]
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
  sess = _pick_target_session(
    request.user,
    session_id=request.data.get("session_id"),
    project_name=request.data.get("project"),
  )
  if not sess:
    return _err("No active timer found", status.HTTP_404_NOT_FOUND)

  sess.start_time = _now()
  sess.is_active = True
  sess.end_time = None
  sess.save()
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
  sess.delete()
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

  project = Projects.objects.filter(
    name=project_name, user=request.user
  ).first()
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
  sess = Sessions.objects.create(
    user=request.user,
    project=project,
    start_time=start_time,
    end_time=end_time,
    is_active=False,
    note=note or None,
  )
  if sub_qs.exists():
    sess.subprojects.add(*list(sub_qs))
  sess.full_clean()
  sess.save()

  return Response(
    _json_ok({"session": _serialize_session(sess, compact)}, compact),
    status=status.HTTP_201_CREATED,
  )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def projects_list_grouped(request):
  """
  List all projects grouped by status.
  Query: start_date?, end_date?, compact?
  """
  compact = _compact(request)
  qp = request.query_params
  start = qp.get("start_date")
  end = qp.get("end_date")

  if start or end:
    projects_qs = Projects.objects.filter(user=request.user)
    projects = in_window(projects_qs, start, end)
  else:
    projects = list(Projects.objects.filter(user=request.user))

  return Response(_serialize_project_grouped(projects, compact))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def subprojects_list(request):
  """
  List subprojects for a given project.
  Query: project (required)
  """
  project_name = request.query_params.get("project") or request.query_params.get(
    "project_name"
  )
  if not project_name:
    return _err("Missing 'project'")

  subprojects = SubProjects.objects.filter(
    parent_project__name=project_name, user=request.user
  )
  compact = _compact(request)
  if compact:
    return Response({"project": project_name, "subprojects": [s.name for s in subprojects]})
  ser = SubProjectSerializer(subprojects, many=True)
  return Response(ser.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def totals(request):
  """
  Show total time spent on a project and its subprojects.
  Query: project (required), start_date?, end_date?, compact?
  """
  compact = _compact(request)
  project_name = request.query_params.get("project")
  if not project_name:
    return _err("Missing 'project'")

  sessions = Sessions.objects.filter(is_active=False, user=request.user)
  sessions = sessions.filter(project__name__iexact=project_name)
  sessions = filter_sessions_by_params(request, sessions)

  # Project total
  proj_total = 0.0
  sub_totals = defaultdict(float)
  for s in sessions:
    dur = s.duration or 0.0
    proj_total += dur
    subs = list(s.subprojects.all())
    if subs:
      for sp in subs:
        sub_totals[sp.name] += dur
    else:
      sub_totals["no subproject"] += dur

  if compact:
    subs = [[k, round(v, 4)] for k, v in sub_totals.items()]
    return Response(
      {"project": project_name, "total": round(proj_total, 4), "subs": subs}
    )
  else:
    return Response(
      {
        "project": project_name,
        "total_minutes": round(proj_total, 4),
        "subprojects": [
          {"name": k, "total_minutes": round(v, 4)}
          for k, v in sub_totals.items()
        ],
      }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def rename_entity(request):
  """
  Rename a project or subproject.
  JSON:
    - Project: { "type": "project", "project": "Old", "new_name": "New" }
    - Subproject: {
        "type": "subproject",
        "project": "Parent",
        "subproject": "OldSub",
        "new_name": "NewSub"
      }
  """
  ent_type = (request.data.get("type") or "").lower()
  new_name = request.data.get("new_name")
  if ent_type not in ("project", "subproject"):
    return _err("type must be 'project' or 'subproject'")
  if not new_name:
    return _err("Missing 'new_name'")

  if ent_type == "project":
    old = request.data.get("project")
    if not old:
      return _err("Missing 'project'")
    proj = get_object_or_404(
      Projects, name=old, user=request.user
    )
    if Projects.objects.filter(user=request.user, name=new_name).exclude(
      pk=proj.pk
    ).exists():
      return _err("Project name already exists", status.HTTP_409_CONFLICT)
    proj.name = new_name
    proj.save()
    return Response({"ok": True, "project": proj.name})

  # subproject
  parent = request.data.get("project")
  sub = request.data.get("subproject")
  if not parent or not sub:
    return _err("Missing 'project' or 'subproject'")
  proj = get_object_or_404(Projects, name=parent, user=request.user)
  sp = get_object_or_404(
    SubProjects, parent_project=proj, user=request.user, name=sub
  )
  if SubProjects.objects.filter(
    user=request.user, parent_project=proj, name=new_name
  ).exclude(pk=sp.pk).exists():
    return _err("Subproject name already exists", status.HTTP_409_CONFLICT)
  sp.name = new_name
  sp.save()
  return Response({"ok": True, "project": parent, "subproject": sp.name})


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def project_delete_body(request):
  """
  Delete a project via JSON body: { "project": "name" }
  """
  name = request.data.get("project")
  if not name:
    return _err("Missing 'project'")
  proj = get_object_or_404(Projects, name=name, user=request.user)
  proj.delete()
  return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def log_activity(request):
  """
  Show activity logs for the week or a given time period.
  Query:
    - period=week|month|day|all
    - start_date?, end_date?
    - project_name?, subproject?, note_snippet?
    - compact?
  """
  compact = _compact(request)
  qp = request.query_params
  period = (qp.get("period") or "").lower()

  sessions = Sessions.objects.filter(is_active=False, user=request.user)

  # Date window
  if period in ("day", "week", "month") and not (qp.get("start_date") or qp.get("end_date")):
    now = timezone.localtime(_now())
    if period == "day":
      start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
      start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
      )
    else:  # month
      start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    sessions = sessions.filter(end_time__gte=start)
  elif period not in ("all", "") or qp.get("start_date") or qp.get("end_date"):
    # Use generic filter util
    sessions = filter_sessions_by_params(request, sessions)

  # Serialize
  if compact:
    logs = [
      {
        "id": s.id,
        "p": s.project.name,
        "subs": [sp.name for sp in s.subprojects.all()],
        "start": s.start_time.isoformat(),
        "end": s.end_time.isoformat() if s.end_time else None,
        "dur": s.duration,
      }
      for s in sessions.order_by("-end_time")
    ]
  else:
    logs = [
      {
        "id": s.id,
        "project": s.project.name,
        "subprojects": [sp.name for sp in s.subprojects.all()],
        "start_time": s.start_time.isoformat(),
        "end_time": s.end_time.isoformat() if s.end_time else None,
        "duration_minutes": s.duration,
        "note": s.note or "",
      }
      for s in sessions.order_by("-end_time")
    ]
  return Response({"count": len(logs), "logs": logs})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mark_project(request):
  """
  Mark a project as active, paused, or complete.
  JSON: { "project": str, "status": "active|paused|complete" }
  """
  project_name = request.data.get("project")
  status_val = (request.data.get("status") or "").lower()
  valid = {k for k, _ in status_choices}
  if status_val not in valid:
    return _err("Invalid status (use: active, paused, complete)")
  proj = get_object_or_404(Projects, name=project_name, user=request.user)
  proj.status = status_val
  proj.save()
  return Response({"ok": True, "project": proj.name, "status": proj.status})


# -----------------------
# Existing endpoints (moved here, small fixes), kept for compatibility
# -----------------------

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_project(request):
  serializer = ProjectSerializer(data=request.data)
  if serializer.is_valid():
    serializer.save(user=request.user)
    return Response(serializer.data)
  return Response(serializer.errors, status=400)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_projects(request):
  qp = request.query_params
  if "start_date" in qp and "end_date" in qp:
    start = qp["start_date"]
    end = qp["end_date"]
    projects_qs = Projects.objects.filter(user=request.user)
    projects = in_window(projects_qs, start, end)
    serializer = ProjectSerializer(projects, many=True)
    return Response(serializer.data)
  elif "start_date" in qp:
    start = qp["start_date"]
    projects_qs = Projects.objects.filter(user=request.user)
    projects = in_window(projects_qs, start)
    serializer = ProjectSerializer(projects, many=True)
    return Response(serializer.data)

  projects = Projects.objects.filter(user=request.user)
  serializer = ProjectSerializer(projects, many=True)
  return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tally_by_sessions(request):
  sessions = Sessions.objects.filter(is_active=False, user=request.user)
  project = request.query_params.get("project_name")
  if project:
    sessions = sessions.filter(project__name=project)
  sessions = filter_sessions_by_params(request, sessions)
  project_durations = tally_project_durations(sessions)
  return Response(project_durations)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tally_by_subprojects(request):
  sessions = Sessions.objects.filter(is_active=False, user=request.user)
  project = request.query_params.get("project_name")
  if project:
    sessions = sessions.filter(project__name__iexact=project)
  sessions = filter_sessions_by_params(request, sessions)

  sub_durations = {}
  for s in sessions:
    dur = s.duration or 0
    subs = list(s.subprojects.all())
    if subs:
      for sub in subs:
        sub_durations.setdefault(sub.name, 0)
        sub_durations[sub.name] += dur
    else:
      sub_durations.setdefault("no subproject", 0)
      sub_durations["no subproject"] += dur

  payload = [{"name": n, "total_time": t} for n, t in sub_durations.items()]
  return Response(payload)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def wordcloud_notes(request):
  from .wordhandler import WordHandler

  handler = WordHandler()
  sessions = Sessions.objects.filter(is_active=False, user=request.user)
  sessions = filter_sessions_by_params(request, sessions)
  notes_text = " ".join([s.note for s in sessions if s.note])

  cleaned = re.sub(r"(\*{1,2}|_{1,2}|~{1,2})", "", notes_text)
  cleaned = re.sub(r"#{1,6}\s", "", cleaned)
  cleaned = re.sub(r"\s+", " ", cleaned).strip()

  seen = defaultdict(int)
  for w in handler.process_list(cleaned.split()):
    seen[w] += 1

  sorted_dict = dict(sorted(seen.items(), key=lambda kv: kv[1], reverse=True))
  return Response(sorted_dict)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def search_projects(request):
  term = request.query_params.get("search_term", "")
  if "status" in request.query_params:
    st = request.query_params["status"]
    projects = Projects.objects.filter(
      name__icontains=term, status=st, user=request.user
    )
  else:
    projects = Projects.objects.filter(
      name__icontains=term, user=request.user
    )
  serializer = ProjectSerializer(projects, many=True)
  return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_project(request, project_name):
  project = get_object_or_404(Projects, name=project_name, user=request.user)
  serializer = ProjectSerializer(project)
  return Response(serializer.data)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_project(request, project_name):
  project = get_object_or_404(Projects, name=project_name, user=request.user)
  project.delete()
  return Response(status=204)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_subproject(request):
  parent_name = request.data.get("parent_project")
  if not parent_name:
    return _err("Missing 'parent_project'")
  if not Projects.objects.filter(name=parent_name, user=request.user).exists():
    return Response(
      {"error": f"Parent project {parent_name} does not exist"}, status=400
    )
  serializer = SubProjectSerializer(data=request.data)
  if serializer.is_valid():
    serializer.save(user=request.user)
    return Response(serializer.data)
  return Response(serializer.errors, status=400)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_subprojects(request, **kwargs):
  project_name = (
    request.query_params.get("project_name") or kwargs.get("project_name")
  )
  subprojects = SubProjects.objects.filter(
    parent_project__name=project_name, user=request.user
  )
  serializer = SubProjectSerializer(subprojects, many=True)
  return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def search_subprojects(request):
  parent_project = request.query_params["project_name"]
  search_term = request.query_params.get("search_term", "")
  subprojects = SubProjects.objects.filter(
    parent_project__name=parent_project,
    name__icontains=search_term,
    user=request.user,
  )
  if not subprojects.exists():
    subprojects = SubProjects.objects.filter(
      parent_project__name=parent_project, user=request.user
    )
  serializer = SubProjectSerializer(subprojects, many=True)
  return Response(serializer.data)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_subproject(request, project_name, subproject_name):
  subproject = get_object_or_404(
    SubProjects,
    name=subproject_name,
    parent_project__name=project_name,
    user=request.user,
  )
  subproject.delete()
  return Response(status=204)


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
  sess = get_object_or_404(Sessions, pk=session_id, user=request.user)
  sess.delete()
  return Response(status=204)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_sessions(request):
  sessions = Sessions.objects.filter(is_active=False, user=request.user)
  sessions = filter_sessions_by_params(request, sessions)
  serializer = SessionSerializer(sessions, many=True)
  # to_representation already compacts project/subprojects as names
  return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_active_sessions(request):
  sessions = Sessions.objects.filter(is_active=True, user=request.user)
  serializer = SessionSerializer(sessions, many=True)
  return Response(serializer.data)


# Needed by list_projects
def in_window(data, start=None, end=None):
  from .utils import in_window as _inw
  return _inw(data, start, end)
