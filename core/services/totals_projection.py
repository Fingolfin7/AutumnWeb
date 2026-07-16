"""Cached project and subproject totals derived from session contributions."""

from dataclasses import dataclass

from django.db.models import F

from core.models import Projects, Sessions, SubProjects


@dataclass(frozen=True)
class SessionContribution:
    project_id: int
    subproject_ids: frozenset[int]
    minutes: float


def _add_delta(deltas, object_id, amount):
    if object_id and amount:
        deltas[object_id] = deltas.get(object_id, 0.0) + amount


class CachedTotalsProjection:
    """Maintain cached totals and last-updated values without instance state."""

    @staticmethod
    def snapshot(session: Sessions) -> SessionContribution:
        minutes = (
            float(session.duration or 0.0)
            if not session.is_active and session.end_time
            else 0.0
        )
        subproject_ids = frozenset(
            session.subprojects.values_list("pk", flat=True)
        )
        return SessionContribution(session.project_id, subproject_ids, minutes)

    @staticmethod
    def apply_change(before, after):
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

    @staticmethod
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
