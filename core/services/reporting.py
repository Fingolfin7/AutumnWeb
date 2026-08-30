"""Small, timezone-explicit reporting primitives for notification reviews."""

from __future__ import annotations

from django.db.models import Count, DurationField, ExpressionWrapper, F, Sum
from django.utils import timezone

from core.models import Sessions


def _aware_range(start, end):
    if timezone.is_naive(start) or timezone.is_naive(end):
        raise ValueError("reporting ranges must use timezone-aware instants")
    if end < start:
        raise ValueError("range end must not precede range start")
    return start, end


def _duration_expression():
    return ExpressionWrapper(
        F("end_time") - F("start_time"), output_field=DurationField()
    )


def summarize_completed_sessions(user, start, end) -> dict:
    """Summarize completed sessions in ``[start, end)``.

    The range is deliberately supplied as aware instants by the weekly-review
    caller.  No active/request timezone is consulted, and an end exactly at
    ``end`` belongs to the following range.
    """
    start, end = _aware_range(start, end)
    sessions = Sessions.objects.filter(
        user=user,
        end_time__isnull=False,
        end_time__gte=start,
        end_time__lt=end,
    )
    aggregate = sessions.aggregate(
        total=Sum(_duration_expression()),
        session_count=Count("pk"),
    )
    duration = aggregate["total"]
    total_minutes = round(duration.total_seconds() / 60, 2) if duration else 0.0
    project_count = sessions.values("project_id").distinct().count()
    per_project = []
    for row in sessions.values("project_id", "project__name").annotate(
        total=Sum(_duration_expression()),
        session_count=Count("pk"),
    ):
        project_duration = row["total"]
        per_project.append(
            {
                "project_id": row["project_id"],
                "project_name": row["project__name"],
                "total_minutes": (
                    round(project_duration.total_seconds() / 60, 2)
                    if project_duration
                    else 0.0
                ),
                "session_count": row["session_count"],
            }
        )
    per_project.sort(
        key=lambda row: (
            -row["total_minutes"],
            row["project_name"] or "",
            row["project_id"],
        )
    )
    return {
        "start": start,
        "end": end,
        "total_minutes": total_minutes,
        "project_count": project_count,
        "session_count": aggregate["session_count"],
        "per_project": per_project,
    }


weekly_completed_session_summary = summarize_completed_sessions
