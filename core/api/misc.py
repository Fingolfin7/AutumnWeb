from __future__ import annotations
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from core.models import Projects, SubProjects, Sessions
from django.db import transaction
from core.api.helpers import _bool


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def audit(request):
    """Recompute total_time for all of the user's projects and subprojects.

    Send {"dry_run": true} or ?dry_run=true to preview without persisting.
    """
    dry_run = _bool(
        request.data.get("dry_run")
        if hasattr(request, "data") and "dry_run" in request.data
        else request.query_params.get("dry_run"),
        False,
    )
    projects = Projects.objects.filter(user=request.user)

    proj_total_delta = 0.0
    proj_changed = 0
    changed_projects = []
    for p in projects:
        before = float(p.total_time or 0.0)
        after = float(
            sum(
                session.duration
                for session in p.sessions.filter(is_active=False)
                if session.duration is not None
            )
        )
        delta = after - before
        if abs(delta) > 1e-9:
            proj_changed += 1
            proj_total_delta += delta
            changed_projects.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "before": round(before, 4),
                    "after": round(after, 4),
                    "delta": round(delta, 4),
                }
            )
            if not dry_run:
                p.total_time = after
                p.save(update_fields=["total_time"])

    subprojects = SubProjects.objects.filter(user=request.user)

    sub_total_delta = 0.0
    sub_changed = 0
    changed_subprojects = []
    for sp in subprojects:
        before = float(sp.total_time or 0.0)
        after = float(
            sum(
                session.duration
                for session in sp.sessions.filter(is_active=False)
                if session.duration is not None
            )
        )
        delta = after - before
        if abs(delta) > 1e-9:
            sub_changed += 1
            sub_total_delta += delta
            changed_subprojects.append(
                {
                    "id": sp.id,
                    "name": sp.name,
                    "project_id": sp.parent_project_id,
                    "project": sp.parent_project.name,
                    "before": round(before, 4),
                    "after": round(after, 4),
                    "delta": round(delta, 4),
                }
            )
            if not dry_run:
                sp.total_time = after
                sp.save(update_fields=["total_time"])

    return Response(
        {
            "ok": True,
            "dry_run": dry_run,
            "projects": {
                "count": projects.count(),
                "changed": proj_changed,
                "delta": round(proj_total_delta, 4),
            },
            "changed_projects": changed_projects,
            "subprojects": {
                "count": subprojects.count(),
                "changed": sub_changed,
                "delta": round(sub_total_delta, 4),
            },
            "changed_subprojects": changed_subprojects,
        },
        status=200,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    """Return info about the authenticated user.

    Includes active_session_count for status indicators.
    """
    u = request.user
    active_session_count = Sessions.objects.filter(user=u, is_active=True).count()
    return Response(
        {
            "ok": True,
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "first_name": getattr(u, "first_name", "") or "",
            "last_name": getattr(u, "last_name", "") or "",
            "active_session_count": active_session_count,
        }
    )
