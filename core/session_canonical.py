"""Canonical client-owned session content used for UUID deduplication."""

from datetime import timezone as datetime_timezone

from django.utils import timezone


def canonical_instant(value):
    if value is None:
        return None
    if timezone.is_naive(value):
        value = value.replace(tzinfo=datetime_timezone.utc)
    return value.astimezone(datetime_timezone.utc).replace(microsecond=0)


def canonical_session_content(
    project_name,
    start,
    end,
    note,
    allocation_mode,
    allocations,
):
    """Return the portable equality tuple for a completed session."""
    return (
        project_name,
        canonical_instant(start),
        canonical_instant(end),
        note or "",
        allocation_mode,
        tuple(sorted(set(allocations))),
    )


def canonical_existing_session(session):
    allocations = (
        (link.subproject.name, link.allocation_bp)
        for link in session.subproject_links.select_related("subproject")
    )
    return canonical_session_content(
        session.project.name,
        session.start_time,
        session.end_time,
        session.note,
        session.allocation_mode,
        allocations,
    )
