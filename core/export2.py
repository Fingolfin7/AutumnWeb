"""Portable, deterministic export format 2."""

from collections import defaultdict
from datetime import timezone as datetime_timezone

from django.db.models import Prefetch, QuerySet
from django.utils import timezone

from core.models import SessionSubproject, SubProjects, Tag


def _utc_seconds(value):
    if timezone.is_naive(value):
        value = value.replace(tzinfo=datetime_timezone.utc)
    return value.astimezone(datetime_timezone.utc).replace(microsecond=0).isoformat()


def build_format2_export(sessions_queryset):
    """Build a deterministic format-2 document from completed sessions."""
    if isinstance(sessions_queryset, QuerySet):
        sessions_queryset = sessions_queryset.prefetch_related(None).select_related(
            "project", "project__context"
        ).prefetch_related(
            Prefetch("project__tags", queryset=Tag.objects.order_by("name", "id")),
            Prefetch(
                "project__subprojects",
                queryset=SubProjects.objects.order_by("name", "id"),
            ),
            Prefetch(
                "subproject_links",
                queryset=SessionSubproject.objects.select_related(
                    "subproject"
                ).order_by("subproject__name", "subproject_id"),
            ),
        )

    sessions_by_project = defaultdict(list)
    for session in sessions_queryset:
        sessions_by_project[session.project.name].append(session)

    projects = []
    for project_name in sorted(sessions_by_project):
        sessions = sorted(
            sessions_by_project[project_name],
            key=lambda session: (session.start_time, session.id),
        )
        project = sessions[0].project
        projects.append(
            {
                "name": project.name,
                "status": project.status,
                "description": project.description or "",
                "context": project.context.name if project.context else None,
                "tags": sorted(tag.name for tag in project.tags.all()),
                "start_date": _utc_seconds(project.start_date),
                "subprojects": [
                    {
                        "name": subproject.name,
                        "description": subproject.description or "",
                    }
                    for subproject in project.subprojects.all()
                ],
                "sessions": [
                    {
                        "uuid": str(session.uuid) if session.uuid else None,
                        "start": _utc_seconds(session.start_time),
                        "end": _utc_seconds(session.end_time),
                        "note": session.note,
                        "links": [
                            {
                                "subproject": link.subproject.name,
                                "allocation_bp": link.allocation_bp,
                            }
                            for link in session.subproject_links.all()
                        ],
                    }
                    for session in sessions
                ],
            }
        )

    return {"format": 2, "projects": projects}
