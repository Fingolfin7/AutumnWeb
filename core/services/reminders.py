"""Transactional timer reminder domain operations.

This module deliberately stops at durable database work. Push network calls
belong to a worker consuming ``NotificationEvent`` rows after commit.
"""

from datetime import datetime, timedelta, timezone as dt_timezone
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import OperationalError, transaction
from django.utils import timezone

from core.models import NotificationEvent, Sessions, TimerReminder


MIN_INTERVAL_SECONDS = 60
MODE_CHOICES = {"after", "at", "interval"}


def _floor_instant(value):
    if isinstance(value, datetime):
        return value.replace(microsecond=0)
    return value


def _canonical_instant(value):
    """Return a whole-second UTC instant for durable scheduling keys."""
    value = _floor_instant(value)
    if isinstance(value, datetime) and timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_default_timezone())
    if isinstance(value, datetime):
        return value.astimezone(dt_timezone.utc)
    return value


def _user_timezone(user):
    name = getattr(getattr(user, "profile", None), "timezone", None)
    try:
        return ZoneInfo(name or settings.TIME_ZONE)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        return ZoneInfo(settings.TIME_ZONE)


def _local_to_utc(value, user):
    """Convert a profile-local wall time, rejecting DST gaps/folds."""
    if not isinstance(value, datetime):
        raise ValidationError({"at": "Enter a valid local date and time."})
    if timezone.is_aware(value):
        return _canonical_instant(value.astimezone(dt_timezone.utc))

    local_tz = _user_timezone(user)
    candidates = []
    for fold in (0, 1):
        candidate = value.replace(tzinfo=local_tz, fold=fold)
        round_trip = candidate.astimezone(dt_timezone.utc).astimezone(local_tz)
        if round_trip.replace(tzinfo=None) == value:
            candidates.append(candidate)
    if not candidates:
        raise ValidationError({"at": "That local time does not exist in the profile timezone."})
    if len(candidates) > 1 and candidates[0].utcoffset() != candidates[1].utcoffset():
        raise ValidationError({"at": "That local time is ambiguous in the profile timezone."})
    return _canonical_instant(candidates[0].astimezone(dt_timezone.utc))


def _duration(amount, unit):
    if amount is None or unit is None:
        raise ValidationError({"amount": "A positive amount and unit are required."})
    try:
        amount = float(amount)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValidationError({"amount": "Enter a positive numeric amount."}) from exc
    if amount <= 0 or amount != amount:
        raise ValidationError({"amount": "Enter a positive numeric amount."})
    unit = str(unit).strip().lower()
    if unit not in {"minute", "minutes", "min", "m", "hour", "hours", "hr", "h"}:
        raise ValidationError({"unit": "Unit must be minutes or hours."})
    seconds = amount * (3600 if unit in {"hour", "hours", "hr", "h"} else 60)
    if seconds < 1 or seconds > 365 * 24 * 60 * 60:
        raise ValidationError({"amount": "Reminder duration is outside the supported range."})
    return int(seconds)


def _elapsed_label(seconds):
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    if minutes:
        return f"{minutes}m"
    return f"{seconds}s"


def _message_for(session, occurrence, template=""):
    project = session.project.name
    elapsed = _elapsed_label((occurrence - session.start_time).total_seconds())
    if template:
        return template.replace("{project}", project).replace("{elapsed}", elapsed)
    return f"{project}: {elapsed} elapsed."


def _payload(session, reminder, occurrence):
    return {
        "title": f"{session.project.name} timer reminder",
        "body": _message_for(session, occurrence, reminder.message),
        "session_id": session.pk,
        "session_uuid": str(session.uuid) if session.uuid else None,
        "reminder_id": reminder.pk,
        "scheduled_at": occurrence.isoformat(),
        "url": f"/timers/#timer-{session.pk}",
    }


@transaction.atomic
def create_timer_reminder(
    *, user, session, mode, amount=None, unit=None, at_local=None, message=""
):
    """Create an owned reminder, locking the timer against concurrent stop."""
    try:
        session_id = getattr(session, "pk", session)
        session = Sessions.objects.select_for_update().get(pk=session_id, user=user)
    except (TypeError, ValueError, Sessions.DoesNotExist) as exc:
        raise ValidationError({"session": "Session does not belong to this user."}) from exc
    if session.end_time is not None:
        raise ValidationError({"session": "Reminders can only be attached to active timers."})
    mode = str(mode or "").strip().lower()
    if mode not in MODE_CHOICES:
        raise ValidationError({"mode": "Unknown reminder mode."})

    start = _floor_instant(session.start_time)
    if mode == "at":
        if at_local is None:
            raise ValidationError({"at": "An at date and time is required."})
        next_fire_at = _local_to_utc(at_local, user)
        interval_seconds = None
    else:
        duration_seconds = _duration(amount, unit)
        if mode == "interval" and duration_seconds < MIN_INTERVAL_SECONDS:
            raise ValidationError({"amount": "Intervals must be at least one minute."})
        next_fire_at = _floor_instant(start + timedelta(seconds=duration_seconds))
        interval_seconds = duration_seconds if mode == "interval" else None

    if mode == "at" and next_fire_at <= _canonical_instant(timezone.now()):
        raise ValidationError({"at": "Reminder time must be in the future."})

    reminder = TimerReminder(
        session=session,
        mode=mode,
        next_fire_at=next_fire_at,
        interval_seconds=interval_seconds,
        message=(message or "").strip(),
    )
    reminder.full_clean()
    reminder.save()
    return reminder


@transaction.atomic
def cancel_timer_reminders(session, *, cancelled_at=None):
    """Cancel active rules while the caller's session lock is held."""
    cancelled_at = _canonical_instant(cancelled_at or timezone.now())
    TimerReminder.objects.filter(session=session, active=True).update(
        active=False,
        next_fire_at=None,
        cancelled_at=cancelled_at,
    )


def _event_for_occurrence(session, reminder, occurrence):
    occurrence = _canonical_instant(occurrence)
    dedupe_key = f"reminder:{reminder.pk}:{occurrence.isoformat()}"
    event, _ = NotificationEvent.objects.get_or_create(
        dedupe_key=dedupe_key,
        defaults={
            "event_type": "reminder",
            "user_id": session.user_id,
            "session_id": session.pk,
            "reminder_id": reminder.pk,
            "payload": _payload(session, reminder, occurrence),
            "scheduled_at": occurrence,
        },
    )
    return event


def _claim_one_reminder(reminder_id, now):
    """Claim one candidate in a short transaction and return its event."""
    with transaction.atomic():
        try:
            unlocked = TimerReminder.objects.get(pk=reminder_id)
            # PostgreSQL serializes this with the canonical session-stop path;
            # SQLite treats it as a no-op, where the reminder CAS below is the
            # correctness mechanism.
            session = Sessions.objects.select_for_update().get(pk=unlocked.session_id)
            reminder = TimerReminder.objects.get(pk=reminder_id)
        except TimerReminder.DoesNotExist:
            return None
        except Sessions.DoesNotExist:
            return None
        if (
            not reminder.active
            or reminder.next_fire_at is None
            or session.end_time is not None
        ):
            return None
        old_next_fire_at = reminder.next_fire_at
        occurrence = _canonical_instant(old_next_fire_at)
        if occurrence > now:
            return None

        if reminder.mode == "interval":
            interval = timedelta(seconds=reminder.interval_seconds)
            # Advance past every elapsed slot, including the one being
            # claimed, so a delayed worker emits one event and never a
            # catch-up burst.
            missed = int((now - occurrence).total_seconds() // interval.total_seconds()) + 1
            next_fire_at = _canonical_instant(occurrence + missed * interval)
            active = True
        else:
            next_fire_at = None
            active = False

        # Compare-and-set is the actual claim. Two workers may have read the
        # same candidate, but only one can advance this exact old schedule and
        # therefore create the event for this occurrence.
        claimed = TimerReminder.objects.filter(
            pk=reminder.pk,
            active=True,
            next_fire_at=old_next_fire_at,
            session__end_time__isnull=True,
        ).update(
            last_fired_at=occurrence,
            next_fire_at=next_fire_at,
            active=active,
        )
        if not claimed:
            return None
        return _event_for_occurrence(session, reminder, occurrence)


def _retry_locked(operation):
    """Retry the transient lock error SQLite raises under a worker race."""
    for attempt in range(8):
        try:
            return operation()
        except OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 7:
                raise
            time.sleep(0.02 * (attempt + 1))


def claim_due_reminders(*, now=None, limit=100):
    """Claim due rules and create at most one event per due rule.

    Candidate IDs are read without locks. Each candidate is claimed with a
    conditional update on its old schedule, so this works on SQLite as well as
    PostgreSQL and does not depend on ``skip_locked``. The unique event key is
    the final portable dedupe guard for retries after a worker crash.
    """
    now = _canonical_instant(now or timezone.now())
    candidate_ids = _retry_locked(
        lambda: list(
            TimerReminder.objects.filter(
                active=True,
                next_fire_at__isnull=False,
                next_fire_at__lte=now,
                session__end_time__isnull=True,
            )
            .order_by("next_fire_at", "pk")
            .values_list("pk", flat=True)[:limit]
        )
    )
    events = []
    for reminder_id in candidate_ids:
        event = _retry_locked(lambda: _claim_one_reminder(reminder_id, now))
        if event is not None:
            events.append(event)
    return events


def enqueue_auto_stop_event(session, occurred_at):
    """Create the one durable auto-stop event for an opted-in timer."""
    occurred_at = _canonical_instant(occurred_at)
    dedupe_key = f"autostop:{session.pk}:{occurred_at.isoformat()}"
    return NotificationEvent.objects.get_or_create(
        dedupe_key=dedupe_key,
        defaults={
            "event_type": "auto_stop",
            "user_id": session.user_id,
            "session_id": session.pk,
            "payload": {
                "title": f"{session.project.name} timer stopped",
                "body": (
                    f"{session.project.name} stopped automatically after "
                    f"{_elapsed_label((occurred_at - session.start_time).total_seconds())}."
                ),
                "session_id": session.pk,
                "session_uuid": str(session.uuid) if session.uuid else None,
                "scheduled_at": occurred_at.isoformat(),
                "url": f"/timers/#timer-{session.pk}",
            },
            "scheduled_at": occurred_at,
        },
    )[0]


dispatch_due_reminders = claim_due_reminders
cancel_session_reminders = cancel_timer_reminders
