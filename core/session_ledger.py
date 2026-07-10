"""Atomic mutations for sessions and their cached project totals.

Session rows are the ledger.  Projects and subprojects cache totals for fast
display, so every normal session mutation goes through this module and applies
only the contribution difference for the affected buckets.
"""

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F

from core.models import Projects, Sessions, SubProjects


UNSET = object()


@dataclass(frozen=True)
class SessionContribution:
    project_id: int
    subproject_ids: frozenset[int]
    minutes: float


def snapshot_contribution(session: Sessions) -> SessionContribution:
    minutes = (
        float(session.duration or 0.0)
        if not session.is_active and session.end_time
        else 0.0
    )
    subproject_ids = frozenset(
        session.subprojects.values_list("pk", flat=True)
    )
    return SessionContribution(session.project_id, subproject_ids, minutes)


def _validate_buckets(session, subprojects):
    if session.project.user_id != session.user_id:
        raise ValidationError("Session project must belong to the session user.")

    invalid = [
        subproject.name
        for subproject in subprojects
        if (
            subproject.user_id != session.user_id
            or subproject.parent_project_id != session.project_id
        )
    ]
    if invalid:
        raise ValidationError(
            "Session subprojects must belong to its project and user: "
            + ", ".join(invalid)
        )


def _add_delta(deltas, object_id, amount):
    if object_id and amount:
        deltas[object_id] = deltas.get(object_id, 0.0) + amount


def apply_contribution_change(before, after):
    project_deltas = {}
    subproject_deltas = {}

    if before is not None:
        _add_delta(project_deltas, before.project_id, -before.minutes)
        for subproject_id in before.subproject_ids:
            _add_delta(subproject_deltas, subproject_id, -before.minutes)

    if after is not None:
        _add_delta(project_deltas, after.project_id, after.minutes)
        for subproject_id in after.subproject_ids:
            _add_delta(subproject_deltas, subproject_id, after.minutes)

    # Deterministic lock order avoids A->B and B->A edits deadlocking.
    for project_id in sorted(project_deltas):
        delta = project_deltas[project_id]
        if delta:
            Projects.objects.filter(pk=project_id).update(
                total_time=F("total_time") + delta
            )

    for subproject_id in sorted(subproject_deltas):
        delta = subproject_deltas[subproject_id]
        if delta:
            SubProjects.objects.filter(pk=subproject_id).update(
                total_time=F("total_time") + delta
            )


def advance_last_updated(session):
    if session.is_active or not session.end_time:
        return
    Projects.objects.filter(
        pk=session.project_id, last_updated__lt=session.end_time
    ).update(last_updated=session.end_time)
    SubProjects.objects.filter(
        pk__in=session.subprojects.values_list("pk", flat=True),
        last_updated__lt=session.end_time,
    ).update(last_updated=session.end_time)


@transaction.atomic
def create_session(*, subprojects=(), **fields):
    """Create a session and add its completed contribution once."""
    session = Sessions(**fields)
    subprojects = list(subprojects)
    _validate_buckets(session, subprojects)
    session.full_clean()
    session.save()
    session.subprojects.set(subprojects)
    after = snapshot_contribution(session)
    apply_contribution_change(None, after)
    advance_last_updated(session)
    return session


@transaction.atomic
def mutate_session(
    session_id,
    *,
    user=None,
    project=UNSET,
    subprojects=UNSET,
    start_time=UNSET,
    end_time=UNSET,
    auto_stop_at=UNSET,
    note=UNSET,
    is_active=UNSET,
):
    """Edit an existing row in place and atomically move its contribution."""
    queryset = Sessions.objects.select_for_update()
    if user is not None:
        queryset = queryset.filter(user=user)
    session = queryset.get(pk=session_id)
    before = snapshot_contribution(session)

    updates = {
        "project": project,
        "start_time": start_time,
        "end_time": end_time,
        "auto_stop_at": auto_stop_at,
        "note": note,
        "is_active": is_active,
    }
    for field, value in updates.items():
        if value is not UNSET:
            setattr(session, field, value)

    final_subprojects = (
        list(session.subprojects.all())
        if subprojects is UNSET
        else list(subprojects)
    )
    _validate_buckets(session, final_subprojects)
    session.full_clean()
    session.save()
    if subprojects is not UNSET:
        session.subprojects.set(final_subprojects)

    after = snapshot_contribution(session)
    apply_contribution_change(before, after)
    advance_last_updated(session)
    return session


@transaction.atomic
def delete_session(session_id, *, user=None):
    """Delete a session and remove exactly its current contribution."""
    queryset = Sessions.objects.select_for_update()
    if user is not None:
        queryset = queryset.filter(user=user)
    session = queryset.get(pk=session_id)
    before = snapshot_contribution(session)
    deleted_id = session.pk
    session.delete()
    apply_contribution_change(before, None)
    return deleted_id
