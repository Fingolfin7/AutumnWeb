"""Atomic mutations for session rows."""

from datetime import datetime
import time

from django.core.exceptions import ValidationError
from django.db import OperationalError, transaction
from django.db.models import F

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


def _validate_allocations(session, allocations):
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
    if sum(allocation_bp for _, allocation_bp in allocations) > 10000:
        raise ValidationError("Session allocations must not exceed 10000 basis points.")


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
            split = even_split_bps(subproject.pk for subproject in subprojects)
            allocations = [(subproject, split[subproject.pk]) for subproject in subprojects]
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
        allocations=UNSET,
        notify_on_auto_stop=UNSET,
        auto_stop=False,
        expected_version=None,
    ):
        """Edit an existing row in place."""
        queryset = Sessions.objects.select_for_update()
        if user is not None:
            queryset = queryset.filter(user=user)
        session = queryset.get(pk=session_id)
        if expected_version is not None and (session.version or 1) != expected_version:
            raise StaleVersionError(session)
        was_active = session.end_time is None
        # is_active is accepted for caller compatibility but ignored: the
        # column was dropped in S12 and the state derives from end_time.
        updates = {
            "project": project,
            "start_time": _floor_instant(start_time),
            "end_time": _floor_instant(end_time),
            "auto_stop_at": _floor_instant(auto_stop_at),
            "note": note,
            "notify_on_auto_stop": notify_on_auto_stop,
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
            split = even_split_bps(subproject.pk for subproject in final_subprojects)
            _set_allocations(
                session,
                [(subproject, split[subproject.pk]) for subproject in final_subprojects],
            )

        _mark_commitments_dirty(session.user_id)
        if was_active and session.end_time is not None:
            from core.services.reminders import cancel_timer_reminders, enqueue_auto_stop_event

            cancel_timer_reminders(session, cancelled_at=session.end_time)
            if auto_stop and session.notify_on_auto_stop:
                enqueue_auto_stop_event(session, session.end_time)
        return session

    @staticmethod
    def auto_stop_session(session_id, *, user=None, now=None):
        """Stop one timer with a portable compare-and-set transition.

        ``select_for_update`` is not a lock on SQLite. Reading the deadline
        and then saving the row would therefore allow two workers to both
        report a stop. The conditional update below is the claim: exactly one
        worker can replace the same active deadline with a completed session.
        All outbox work remains inside this transaction and is only delivered
        later by the dispatcher.
        """
        from django.utils import timezone

        now = now or timezone.now()
        if timezone.is_naive(now):
            now = timezone.make_aware(now)
        for attempt in range(4):
            try:
                with transaction.atomic():
                    queryset = Sessions.objects.filter(
                        pk=session_id,
                        end_time__isnull=True,
                        auto_stop_at__isnull=False,
                        auto_stop_at__lte=now,
                    )
                    if user is not None:
                        queryset = queryset.filter(user=user)
                    stored_deadline = queryset.values_list("auto_stop_at", flat=True).first()
                    if stored_deadline is None:
                        return None
                    deadline = _floor_instant(stored_deadline)
                    claimed = queryset.filter(auto_stop_at=stored_deadline).update(
                        end_time=deadline,
                        auto_stop_at=None,
                        version=F("version") + 1,
                    )
                    if claimed != 1:
                        return None

                    session = Sessions.objects.select_related("project").get(
                        pk=session_id
                    )
                    _mark_commitments_dirty(session.user_id)
                    from core.services.reminders import (
                        cancel_timer_reminders,
                        enqueue_auto_stop_event,
                    )

                    cancel_timer_reminders(session, cancelled_at=deadline)
                    if session.notify_on_auto_stop:
                        enqueue_auto_stop_event(session, deadline)
                    return session
            except OperationalError:
                if attempt == 3:
                    raise
                # SQLite uses a short busy timeout, but a second worker may
                # still observe a transient table lock while the first worker
                # commits its outbox update. Retry the CAS after that commit.
                time.sleep(0.01 * (attempt + 1))

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
        from core.services.reminders import cancel_timer_reminders

        cancel_timer_reminders(session)
        deleted_id = session.pk
        user_id = session.user_id
        session.delete()
        _mark_commitments_dirty(user_id)
        return deleted_id

    @staticmethod
    @transaction.atomic
    def set_allocations(session_id, *, user, allocations, expected_version=None):
        """Replace the complete allocation set for one session."""
        session = (
            Sessions.objects.select_for_update()
            .select_related("project")
            .get(pk=session_id, user=user)
        )
        if expected_version is not None and (session.version or 1) != expected_version:
            raise StaleVersionError(session)
        allocations = list(allocations)

        subprojects = [subproject for subproject, _ in allocations]
        _validate_buckets(session, subprojects)
        _validate_allocations(session, allocations)

        session.version = (session.version or 1) + 1
        session.full_clean()
        _set_allocations(session, allocations)
        session.save(update_fields=["version"])
        _mark_commitments_dirty(session.user_id)
        return session

    @staticmethod
    @transaction.atomic
    def replace_subprojects(session_id, *, user, subprojects):
        """Replace a session's complete subproject link set."""
        return SessionMutationService.mutate_session(
            session_id, user=user, subprojects=subprojects
        )
