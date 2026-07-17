"""Atomic mutations for session rows."""

from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import transaction

from core.models import Commitment, Sessions, SessionSubproject
UNSET = object()


class StaleVersionError(Exception):
    """Optimistic-concurrency check failed against the freshly-locked row.

    Carries the locked instance as ``.current`` so callers can build a
    409 conflict response from authoritative post-lock state.
    """

    def __init__(self, current):
        self.current = current
        super().__init__("The row changed since the supplied version.")


def even_split_bps(subproject_ids):
    """Return a deterministic 10,000-bp split keyed by subproject id."""
    sorted_ids = sorted(subproject_ids)
    if not sorted_ids:
        return {}
    quotient, remainder = divmod(10000, len(sorted_ids))
    split = {subproject_id: quotient for subproject_id in sorted_ids}
    split[sorted_ids[0]] += remainder
    return split


def _mark_commitments_dirty(user_id):
    Commitment.objects.filter(user_id=user_id).update(needs_recompute=True)


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


def _set_allocations(session, allocations):
    SessionSubproject.objects.filter(session=session).delete()
    SessionSubproject.objects.bulk_create(
        [
            SessionSubproject(
                session=session,
                subproject=subproject,
                allocation_bp=allocation_bp,
            )
            for subproject, allocation_bp in allocations
        ]
    )


def _validate_allocations(session, allocations, allocation_mode=None):
    allocation_mode = allocation_mode or session.allocation_mode
    subproject_ids = [subproject.pk for subproject, _ in allocations]
    if len(subproject_ids) != len(set(subproject_ids)):
        raise ValidationError("Session allocations must have unique subprojects.")
    invalid_bp = [
        allocation_bp
        for _, allocation_bp in allocations
        if (
            isinstance(allocation_bp, bool)
            or not isinstance(allocation_bp, int)
            or not 1 <= allocation_bp <= 10000
        )
    ]
    if invalid_bp:
        raise ValidationError("Session allocations must be from 1 to 10000 basis points.")
    if allocation_mode == "legacy_full" and any(
        allocation_bp != 10000 for _, allocation_bp in allocations
    ):
        raise ValidationError("legacy_full session allocations must equal 10000.")
    if (
        allocation_mode == "partitioned"
        and sum(allocation_bp for _, allocation_bp in allocations) > 10000
    ):
        raise ValidationError("Partitioned session allocations must not exceed 10000.")


class SessionMutationService:
    """The single atomic write path for session rows."""

    @staticmethod
    @transaction.atomic
    def create_session(*, subprojects=(), allocations=None, **fields):
        """Create a session."""
        session = Sessions(**fields)
        allocations = None if allocations is None else list(allocations)
        subprojects = (
            list(subprojects)
            if allocations is None
            else [subproject for subproject, _ in allocations]
        )
        session.start_time = _floor_instant(session.start_time)
        session.end_time = _floor_instant(session.end_time)
        session.auto_stop_at = _floor_instant(session.auto_stop_at)
        _validate_buckets(session, subprojects)
        if allocations is not None:
            _validate_allocations(session, allocations)
        session.full_clean()
        session.save()
        if allocations is None:
            session.subprojects.set(subprojects)
        else:
            _set_allocations(session, allocations)
        _mark_commitments_dirty(session.user_id)
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
        allocation_mode=UNSET,
        allocations=UNSET,
        expected_version=None,
    ):
        """Edit an existing row in place."""
        queryset = Sessions.objects.select_for_update()
        if user is not None:
            queryset = queryset.filter(user=user)
        session = queryset.get(pk=session_id)
        if expected_version is not None and (session.version or 1) != expected_version:
            raise StaleVersionError(session)
        # is_active is accepted for caller compatibility but ignored: the
        # column was dropped in S12 and the state derives from end_time.
        updates = {
            "project": project,
            "start_time": _floor_instant(start_time),
            "end_time": _floor_instant(end_time),
            "auto_stop_at": _floor_instant(auto_stop_at),
            "note": note,
            "allocation_mode": allocation_mode,
        }
        for field, value in updates.items():
            if value is not UNSET:
                setattr(session, field, value)

        if allocations is not UNSET:
            allocations = list(allocations)
            final_subprojects = [subproject for subproject, _ in allocations]
        else:
            final_subprojects = (
                list(session.subprojects.all())
                if subprojects is UNSET
                else list(subprojects)
            )
        _validate_buckets(session, final_subprojects)
        if allocations is not UNSET:
            _validate_allocations(session, allocations)
        session.version = (session.version or 1) + 1
        session.full_clean()
        session.save()
        if allocations is not UNSET:
            _set_allocations(session, allocations)
        elif subprojects is not UNSET:
            session.subprojects.set(final_subprojects)

        _mark_commitments_dirty(session.user_id)
        return session

    @staticmethod
    @transaction.atomic
    def delete_session(session_id, *, user=None, expected_version=None):
        """Delete a session."""
        queryset = Sessions.objects.select_for_update()
        if user is not None:
            queryset = queryset.filter(user=user)
        session = queryset.get(pk=session_id)
        if expected_version is not None and (session.version or 1) != expected_version:
            raise StaleVersionError(session)
        deleted_id = session.pk
        user_id = session.user_id
        session.delete()
        _mark_commitments_dirty(user_id)
        return deleted_id

    @staticmethod
    @transaction.atomic
    def set_allocations(
        session_id, *, user, allocations, allocation_mode, expected_version=None
    ):
        """Replace the complete allocation set and mode for one session."""
        session = (
            Sessions.objects.select_for_update()
            .select_related("project")
            .get(pk=session_id, user=user)
        )
        if expected_version is not None and (session.version or 1) != expected_version:
            raise StaleVersionError(session)
        allocations = list(allocations)

        if allocation_mode not in {"legacy_full", "partitioned"}:
            raise ValidationError("Invalid session allocation mode.")
        subprojects = [subproject for subproject, _ in allocations]
        _validate_buckets(session, subprojects)
        _validate_allocations(session, allocations, allocation_mode)

        session.allocation_mode = allocation_mode
        session.version = (session.version or 1) + 1
        session.full_clean()
        _set_allocations(session, allocations)
        session.save(update_fields=["allocation_mode", "version"])
        _mark_commitments_dirty(session.user_id)
        return session

    @staticmethod
    @transaction.atomic
    def replace_subprojects(session_id, *, user, subprojects):
        """Replace a session's complete subproject link set."""
        return SessionMutationService.mutate_session(
            session_id, user=user, subprojects=subprojects
        )
