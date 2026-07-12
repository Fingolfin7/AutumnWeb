from __future__ import annotations
from collections import defaultdict
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from core.models import Projects, Sessions, Tag
from core.utils import (
    filter_sessions_by_params,
    tally_project_durations,
    filter_by_active_context,
)
from core.api.helpers import _apply_tag_filters, _compact, _err


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def totals(request):
    """
    Show total time spent on a project and its subprojects.
    Query: project (required), start_date?, end_date?, compact?, context?, tags?
    """
    compact = _compact(request)
    project_name = request.query_params.get("project")
    if not project_name:
        return _err("Missing 'project'")

    sessions = Sessions.objects.filter(is_active=False, user=request.user)
    sessions = sessions.filter(project__name__iexact=project_name)
    sessions = filter_by_active_context(
        sessions, request, override_context_id=request.query_params.get("context")
    )
    sessions = _apply_tag_filters(
        request.query_params, sessions, kind="sessions", user=request.user
    )
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


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tally_by_sessions(request):
    sessions = Sessions.objects.filter(is_active=False, user=request.user)
    project = request.query_params.get("project_name")
    if project:
        sessions = sessions.filter(project__name__iexact=project)
    sessions = filter_by_active_context(
        sessions, request, override_context_id=request.query_params.get("context")
    )
    sessions = _apply_tag_filters(
        request.query_params, sessions, kind="sessions", user=request.user
    )
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
    sessions = filter_by_active_context(
        sessions, request, override_context_id=request.query_params.get("context")
    )
    sessions = _apply_tag_filters(
        request.query_params, sessions, kind="sessions", user=request.user
    )
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
def tally_by_context(request):
    """Aggregate time by context."""
    sessions = Sessions.objects.filter(is_active=False, user=request.user)
    sessions = filter_sessions_by_params(request, sessions)

    context_durations = {}
    for s in sessions:
        dur = s.duration or 0
        context_name = s.project.context.name if s.project.context else "General"
        context_durations.setdefault(context_name, 0)
        context_durations[context_name] += dur

    payload = [{"name": n, "total_time": t} for n, t in context_durations.items()]
    return Response(payload)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tally_by_status(request):
    """Aggregate project count and time by status."""
    user = request.user
    projects = Projects.objects.filter(user=user)

    # Apply context filter if provided
    context_id = request.query_params.get("context")
    if context_id:
        projects = projects.filter(context_id=context_id)

    # Apply tag filters to projects
    projects = _apply_tag_filters(
        request.query_params, projects, kind="projects", user=user
    )

    # Apply exclude filter (by ID from web UI)
    exclude_ids = request.query_params.getlist("exclude_projects")
    if exclude_ids:
        projects = projects.exclude(id__in=exclude_ids)

    # Filter sessions by date range and other params to calculate accurate totals
    sessions = Sessions.objects.filter(is_active=False, user=user)
    sessions = filter_sessions_by_params(request, sessions)

    # Build project time lookup from filtered sessions
    project_times = {}
    for s in sessions:
        pid = s.project_id
        dur = s.duration or 0
        project_times[pid] = project_times.get(pid, 0) + dur

    # Aggregate by status using filtered session times
    status_data = {}
    for p in projects:
        st = p.status
        if st not in status_data:
            status_data[st] = {"status": st, "count": 0, "total_time": 0}
        status_data[st]["count"] += 1
        # Use filtered session time instead of stored total
        status_data[st]["total_time"] += project_times.get(p.id, 0)

    payload = list(status_data.values())
    return Response(payload)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tally_by_tags(request):
    """Aggregate time by tag."""
    user = request.user

    # Filter sessions by date range, context, and other params
    sessions = Sessions.objects.filter(is_active=False, user=user)
    sessions = filter_sessions_by_params(request, sessions)

    # Build tag stats from filtered sessions
    tag_stats = {}  # tag_id -> {total_time, project_ids}
    for s in sessions:
        dur = s.duration or 0
        pid = s.project_id
        # Get tags for this session's project
        project_tags = s.project.tags.all()
        for tag in project_tags:
            if tag.id not in tag_stats:
                tag_stats[tag.id] = {"total_time": 0, "project_ids": set()}
            tag_stats[tag.id]["total_time"] += dur
            tag_stats[tag.id]["project_ids"].add(pid)

    # Get tag objects for the ones that have data
    tags = Tag.objects.filter(user=user, id__in=tag_stats.keys())

    payload = [
        {
            "name": t.name,
            "tag_id": t.id,
            "total_time": tag_stats[t.id]["total_time"],
            "project_count": len(tag_stats[t.id]["project_ids"]),
            "color": t.color or None
        }
        for t in tags
    ]
    return Response(payload)
