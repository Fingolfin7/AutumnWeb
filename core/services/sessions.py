"""Atomic mutations for session rows and their cached total projections."""

from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import transaction

from core.models import Sessions
from core.services.totals_projection import CachedTotalsProjection


UNSET = object()


def _floor_instant(value):
    if isinstance(value, datetime):
        return value.replace(microsecond=0)
    return value


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


class SessionMutationService:
    """The single atomic write path for session rows."""

    @staticmethod
    @transaction.atomic
    def create_session(*, subprojects=(), **fields):
        """Create a session and add its completed contribution once."""
        session = Sessions(**fields)
        subprojects = list(subprojects)
        session.start_time = _floor_instant(session.start_time)
        session.end_time = _floor_instant(session.end_time)
        session.auto_stop_at = _floor_instant(session.auto_stop_at)
        _validate_buckets(session, subprojects)
        session.full_clean()
        session.save()
        session.subprojects.set(subprojects)
        after = CachedTotalsProjection.snapshot(session)
        CachedTotalsProjection.apply_change(None, after)
        CachedTotalsProjection.advance_last_updated(session)
        return session

    @staticmethod
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
        before = CachedTotalsProjection.snapshot(session)

        updates = {
            "project": project,
            "start_time": _floor_instant(start_time),
            "end_time": _floor_instant(end_time),
            "auto_stop_at": _floor_instant(auto_stop_at),
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

        after = CachedTotalsProjection.snapshot(session)
        CachedTotalsProjection.apply_change(before, after)
        CachedTotalsProjection.advance_last_updated(session)
        return session

    @staticmethod
    @transaction.atomic
    def delete_session(session_id, *, user=None):
        """Delete a session and remove exactly its current contribution."""
        queryset = Sessions.objects.select_for_update()
        if user is not None:
            queryset = queryset.filter(user=user)
        session = queryset.get(pk=session_id)
        before = CachedTotalsProjection.snapshot(session)
        deleted_id = session.pk
        session.delete()
        CachedTotalsProjection.apply_change(before, None)
        return deleted_id

    @staticmethod
    @transaction.atomic
    def replace_subprojects(session_id, *, user, subprojects):
        """Replace a session's complete subproject link set."""
        return SessionMutationService.mutate_session(
            session_id, user=user, subprojects=subprojects
        )
