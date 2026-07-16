from __future__ import annotations
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import (
    CharField,
    Count,
    DurationField,
    ExpressionWrapper,
    F,
    Max,
    Min,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from core.attribution import subproject_tally
from core.models import Projects, Sessions
from core.utils import (
    filter_sessions_by_params,
    filter_by_active_context,
)
from core.api.helpers import _apply_tag_filters, _compact, _err


def _duration_expression():
    return ExpressionWrapper(
        F("end_time") - F("start_time"), output_field=DurationField()
    )


def _reanchor_sessions(sessions):
    """Remove join fan-out before aggregating session durations."""
    return Sessions.objects.filter(pk__in=sessions.values("pk")).order_by()


def _minutes(duration):
    return duration.total_seconds() / 60.0 if duration else 0.0


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

    sessions = Sessions.objects.filter(end_time__isnull=False, user=request.user)
    sessions = sessions.filter(project__name__iexact=project_name)
    sessions = filter_by_active_context(
        sessions, request, override_context_id=request.query_params.get("context")
    )
    sessions = _apply_tag_filters(
        request.query_params, sessions, kind="sessions", user=request.user
    )
    sessions = filter_sessions_by_params(request, sessions)

    # Re-anchor on session IDs so M2M filters cannot fan out duration sums.
    base_sessions = Sessions.objects.filter(pk__in=sessions.values("pk"))
    duration_expr = _duration_expression()
    project_rows = base_sessions.values("project_id").annotate(
        total=Sum(duration_expr)
    )
    proj_total = sum(
        row["total"].total_seconds() / 60.0 if row["total"] else 0.0
        for row in project_rows
    )

    # Latest session time preserves the old bucket insertion order. The ID is a
    # deterministic tie-breaker matching the usual M2M relation order.
    sub_rows = subproject_tally(base_sessions, group_by_id=True)
    sub_totals = {}
    for row in sub_rows:
        name = row["name"]
        sub_totals[name] = (
            row["total"].total_seconds() / 60.0 if row["total"] else 0.0
        )

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
    sessions = Sessions.objects.filter(end_time__isnull=False, user=request.user)
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
    base_sessions = _reanchor_sessions(sessions)
    project_durations = [
        {"name": row["project__name"], "total_time": _minutes(row["total"])}
        for row in base_sessions.values("project__name")
        .annotate(total=Sum(_duration_expression()), latest_end_time=Max("end_time"))
        .order_by("-latest_end_time", "project__name")
    ]
    return Response(project_durations)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tally_by_subprojects(request):
    sessions = Sessions.objects.filter(end_time__isnull=False, user=request.user)
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

    base_sessions = _reanchor_sessions(sessions)
    payload = [
        {"name": row["name"], "total_time": _minutes(row["total"])}
        for row in subproject_tally(base_sessions)
    ]
    return Response(payload)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tally_by_context(request):
    """Aggregate time by context."""
    sessions = Sessions.objects.filter(end_time__isnull=False, user=request.user)
    sessions = filter_sessions_by_params(request, sessions)

    base_sessions = _reanchor_sessions(sessions)
    payload = [
        {"name": row["name"], "total_time": _minutes(row["total"])}
        for row in base_sessions.annotate(
            name=Coalesce(
                "project__context__name",
                Value("General"),
                output_field=CharField(),
            )
        )
        .values("name")
        .annotate(total=Sum(_duration_expression()), latest_end_time=Max("end_time"))
        .order_by("-latest_end_time", "name")
    ]
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
    sessions = Sessions.objects.filter(end_time__isnull=False, user=user)
    sessions = filter_sessions_by_params(request, sessions)

    status_counts = list(
        projects.order_by()
        .values("status")
        .annotate(
            count=Count("pk", distinct=True),
            first_project_name=Min("name"),
        )
        .order_by("first_project_name", "status")
    )
    eligible_project_ids = projects.order_by().values("pk")
    status_times = {
        row["project__status"]: _minutes(row["total"])
        for row in _reanchor_sessions(
            sessions.filter(project_id__in=eligible_project_ids)
        )
        .values("project__status")
        .annotate(total=Sum(_duration_expression()))
    }
    payload = [
        {
            "status": row["status"],
            "count": row["count"],
            "total_time": status_times.get(row["status"], 0),
        }
        for row in status_counts
    ]
    return Response(payload)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tally_by_tags(request):
    """Aggregate time by tag."""
    user = request.user

    # Filter sessions by date range, context, and other params
    sessions = Sessions.objects.filter(end_time__isnull=False, user=user)
    sessions = filter_sessions_by_params(request, sessions)

    base_sessions = _reanchor_sessions(sessions)
    payload = [
        {
            "name": row["project__tags__name"],
            "tag_id": row["project__tags__id"],
            "total_time": _minutes(row["total"]),
            "project_count": row["project_count"],
            "color": row["project__tags__color"] or None,
        }
        for row in base_sessions.filter(
            project__tags__isnull=False,
            project__tags__user=user,
        )
        .values(
            "project__tags__id",
            "project__tags__name",
            "project__tags__color",
        )
        .annotate(
            total=Sum(_duration_expression()),
            project_count=Count("project_id", distinct=True),
        )
        .order_by("project__tags__name")
    ]
    return Response(payload)
