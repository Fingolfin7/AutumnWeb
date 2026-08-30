"""Durable scheduling for user-planned and reflective notifications.

This module owns local-wall-time recurrence and short database claims.  It
never performs provider I/O; claimed :class:`NotificationEvent` rows are
delivered by the existing push outbox after these transactions have closed.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone as dt_timezone
import math
import time as time_module
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import OperationalError, transaction
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from core.commitments import get_commitment_actionability, weekly_commitment_score
from core.models import (
    Commitment,
    NotificationEvent,
    NotificationPreference,
    Projects,
    ScheduledReminder,
    SubProjects,
)
from core.services.reporting import summarize_completed_sessions
from core.services.push import validate_notification_payload


SNOOZE_CHOICES = {"15m", "1h", "tomorrow"}
MAX_SCHEDULE_MESSAGE_LENGTH = 240


def _canonical_instant(value):
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_default_timezone())
    return value.astimezone(dt_timezone.utc).replace(microsecond=0)


def user_timezone(user):
    name = getattr(getattr(user, "profile", None), "timezone", None)
    try:
        return ZoneInfo(name or settings.TIME_ZONE)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        return ZoneInfo(settings.TIME_ZONE)


def _zone(value):
    try:
        return value if isinstance(value, ZoneInfo) else ZoneInfo(str(value))
    except (TypeError, ValueError, ZoneInfoNotFoundError) as exc:
        raise ValidationError({"timezone": "Enter a valid IANA timezone."}) from exc


def _wall_candidates(value, zone):
    candidates = []
    for fold in (0, 1):
        candidate = value.replace(tzinfo=zone, fold=fold)
        round_trip = candidate.astimezone(dt_timezone.utc).astimezone(zone)
        if round_trip.replace(tzinfo=None) == value:
            candidates.append(candidate)
    return candidates


def local_wall_to_utc(value, zone_name, *, strict=True):
    """Convert a naive local wall time into a whole-second UTC instant.

    User-entered values are strict.  Automatically advanced recurrences shift
    a DST gap to its first valid minute and choose the earlier side of a fold.
    """

    if not isinstance(value, datetime):
        raise ValidationError({"scheduled_for": "Enter a valid local date and time."})
    if timezone.is_aware(value):
        return _canonical_instant(value)
    zone = _zone(zone_name)
    candidate_value = value.replace(second=0, microsecond=0)
    candidates = _wall_candidates(candidate_value, zone)
    if not candidates and not strict:
        # No civil-time gap is remotely close to a day, but a hard bound keeps
        # malformed timezone data from producing an unbounded loop.
        for _ in range(24 * 60):
            candidate_value += timedelta(minutes=1)
            candidates = _wall_candidates(candidate_value, zone)
            if candidates:
                break
    if not candidates:
        raise ValidationError(
            {"scheduled_for": "That local time does not exist because the clocks move forward."}
        )
    if (
        strict
        and len(candidates) > 1
        and candidates[0].utcoffset() != candidates[1].utcoffset()
    ):
        raise ValidationError(
            {"scheduled_for": "That local time occurs twice because the clocks move back."}
        )
    # fold=0 is the earlier occurrence for an ambiguous wall time.
    return _canonical_instant(candidates[0])


def _local_instant(local_date, local_time, zone, *, strict=False):
    value = datetime.combine(local_date, local_time.replace(tzinfo=None))
    return local_wall_to_utc(value, zone, strict=strict)


def _next_daily_slot(local_time, zone, after):
    after = _canonical_instant(after)
    local_after = after.astimezone(zone)
    candidate = _local_instant(local_after.date(), local_time, zone)
    if candidate <= after:
        candidate = _local_instant(local_after.date() + timedelta(days=1), local_time, zone)
    return candidate


def _next_weekly_slot(weekday, local_time, zone, after):
    after = _canonical_instant(after)
    local_after = after.astimezone(zone)
    days = (int(weekday) - local_after.weekday()) % 7
    candidate_date = local_after.date() + timedelta(days=days)
    candidate = _local_instant(candidate_date, local_time, zone)
    if candidate <= after:
        candidate = _local_instant(candidate_date + timedelta(days=7), local_time, zone)
    return candidate


def _latest_daily_slot(local_time, zone, now):
    now = _canonical_instant(now)
    local_now = now.astimezone(zone)
    candidate = _local_instant(local_now.date(), local_time, zone)
    if candidate > now:
        candidate = _local_instant(local_now.date() - timedelta(days=1), local_time, zone)
    return candidate


def _latest_weekly_slot(weekday, local_time, zone, now):
    now = _canonical_instant(now)
    local_now = now.astimezone(zone)
    days_back = (local_now.weekday() - int(weekday)) % 7
    candidate_date = local_now.date() - timedelta(days=days_back)
    candidate = _local_instant(candidate_date, local_time, zone)
    if candidate > now:
        candidate = _local_instant(candidate_date - timedelta(days=7), local_time, zone)
    return candidate


def ensure_notification_preferences(user, *, now=None):
    """Return preferences and initialize enabled category claim instants."""

    now = _canonical_instant(now or timezone.now())
    preference, _ = NotificationPreference.objects.get_or_create(user=user)
    zone = user_timezone(user)
    updates = []
    if preference.commitment_checks_enabled and preference.next_commitment_check_at is None:
        preference.next_commitment_check_at = _next_daily_slot(
            preference.commitment_check_time, zone, now
        )
        updates.append("next_commitment_check_at")
    if preference.weekly_review_enabled and preference.next_weekly_review_at is None:
        preference.next_weekly_review_at = _next_weekly_slot(
            preference.weekly_review_weekday,
            preference.weekly_review_time,
            zone,
            now,
        )
        updates.append("next_weekly_review_at")
    if updates:
        preference.save(update_fields=[*updates, "updated_at"])
    return preference


def reschedule_notification_preferences(preference, *, now=None):
    """Recompute UTC claim instants after settings or profile-zone changes."""

    now = _canonical_instant(now or timezone.now())
    preference.full_clean()
    zone = user_timezone(preference.user)
    preference.next_commitment_check_at = (
        _next_daily_slot(preference.commitment_check_time, zone, now)
        if preference.commitment_checks_enabled
        else None
    )
    preference.next_weekly_review_at = (
        _next_weekly_slot(
            preference.weekly_review_weekday,
            preference.weekly_review_time,
            zone,
            now,
        )
        if preference.weekly_review_enabled
        else None
    )
    preference.version += 1
    preference.save()
    return preference


def create_scheduled_reminder(
    *,
    user,
    project,
    local_date,
    local_time,
    cadence,
    subproject=None,
    message="",
    timezone_name=None,
    now=None,
):
    now = _canonical_instant(now or timezone.now())
    project_id = getattr(project, "pk", project)
    project = Projects.objects.filter(pk=project_id, user=user).first()
    if project is None:
        raise ValidationError({"project": "Project does not belong to this account."})
    if subproject is not None:
        subproject_id = getattr(subproject, "pk", subproject)
        subproject = SubProjects.objects.filter(
            pk=subproject_id, user=user, parent_project=project
        ).first()
        if subproject is None:
            raise ValidationError(
                {"subproject": "Subproject does not belong to the selected project."}
            )
    timezone_name = str(timezone_name or user_timezone(user).key)
    scheduled_for = local_wall_to_utc(
        datetime.combine(local_date, local_time), timezone_name, strict=True
    )
    if scheduled_for <= now:
        raise ValidationError({"scheduled_for": "The first reminder must be in the future."})
    ensure_notification_preferences(user, now=now)
    reminder = ScheduledReminder(
        user=user,
        project=project,
        subproject=subproject,
        message=str(message or "").strip()[:MAX_SCHEDULE_MESSAGE_LENGTH],
        cadence=str(cadence or "").strip().lower(),
        timezone=timezone_name,
        anchor_date=local_date,
        anchor_time=local_time.replace(second=0, microsecond=0),
        next_fire_at=scheduled_for,
    )
    reminder.full_clean()
    reminder.save()
    return reminder


@transaction.atomic
def update_scheduled_reminder(
    *,
    user,
    reminder_id,
    version,
    project,
    local_date,
    local_time,
    cadence,
    subproject=None,
    message="",
    timezone_name=None,
    now=None,
):
    """Replace an active schedule after an optimistic-version check."""

    now = _canonical_instant(now or timezone.now())
    reminder = ScheduledReminder.objects.select_for_update().filter(
        pk=reminder_id, user=user, active=True
    ).first()
    if reminder is None:
        raise ValidationError({"reminder": "Active scheduled reminder was not found."})
    try:
        submitted_version = int(version)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"version": "Reload this schedule and try again."}) from exc
    if submitted_version != reminder.version:
        raise ValidationError(
            {"version": "This schedule changed in another tab. Reload and try again."}
        )

    project_id = getattr(project, "pk", project)
    project = Projects.objects.filter(pk=project_id, user=user).first()
    if project is None:
        raise ValidationError({"project": "Project does not belong to this account."})
    if subproject is not None:
        subproject_id = getattr(subproject, "pk", subproject)
        subproject = SubProjects.objects.filter(
            pk=subproject_id, user=user, parent_project=project
        ).first()
        if subproject is None:
            raise ValidationError(
                {"subproject": "Subproject does not belong to the selected project."}
            )
    timezone_name = str(timezone_name or user_timezone(user).key)
    next_fire_at = local_wall_to_utc(
        datetime.combine(local_date, local_time), timezone_name, strict=True
    )
    if next_fire_at <= now:
        raise ValidationError({"scheduled_for": "The next reminder must be in the future."})

    reminder.project = project
    reminder.subproject = subproject
    reminder.message = str(message or "").strip()[:MAX_SCHEDULE_MESSAGE_LENGTH]
    reminder.cadence = str(cadence or "").strip().lower()
    reminder.timezone = timezone_name
    reminder.anchor_date = local_date
    reminder.anchor_time = local_time.replace(second=0, microsecond=0)
    reminder.next_fire_at = next_fire_at
    reminder.cancelled_at = None
    reminder.snoozed_until = None
    reminder.version += 1
    reminder.full_clean()
    reminder.save()
    _cancel_pending_schedule_events(reminder)
    return reminder


def _next_reminder_slot(reminder, after):
    if reminder.cadence == "once":
        return None
    zone = _zone(reminder.timezone)
    after = _canonical_instant(after)
    local_after_date = after.astimezone(zone).date()
    step = 1 if reminder.cadence == "daily" else 7
    elapsed_days = max(0, (local_after_date - reminder.anchor_date).days)
    jumps = max(0, elapsed_days // step)
    candidate_date = reminder.anchor_date + timedelta(days=jumps * step)
    candidate = _local_instant(candidate_date, reminder.anchor_time, zone)
    while candidate <= after:
        candidate_date += timedelta(days=step)
        candidate = _local_instant(candidate_date, reminder.anchor_time, zone)
    return candidate


def _start_url(reminder):
    query = {"project_id": reminder.project_id}
    if reminder.subproject_id:
        query["subproject_id"] = reminder.subproject_id
    return f"{reverse('start_timer')}?{urlencode(query)}"


def _scheduled_payload(reminder, occurrence):
    local_occurrence = occurrence.astimezone(_zone(reminder.timezone))
    body = reminder.message.strip() or (
        f"You planned {reminder.project.name} for {local_occurrence:%H:%M}."
    )
    start_url = _start_url(reminder)
    snooze_url = reverse("snooze_scheduled_reminder", args=[reminder.pk])
    return validate_notification_payload({
        "title": "Time to start",
        "body": body,
        "url": start_url,
        "kind": "scheduled_reminder",
        "scheduled_reminder_id": reminder.pk,
        "scheduled_at": occurrence.isoformat(),
        "tag": f"scheduled-reminder-{reminder.pk}-{int(occurrence.timestamp())}",
        "actions": [
            {"action": "start", "title": "Start timer", "url": start_url},
            {"action": "snooze", "title": "Snooze", "url": snooze_url},
        ],
    })


def _cancel_pending_schedule_events(reminder):
    return NotificationEvent.objects.filter(
        scheduled_reminder=reminder, status="pending"
    ).update(status="cancelled", lease_until=None, next_attempt_at=None)


@transaction.atomic
def cancel_scheduled_reminder(*, user, reminder_id, version, now=None):
    now = _canonical_instant(now or timezone.now())
    reminder = ScheduledReminder.objects.select_for_update().filter(
        pk=reminder_id, user=user
    ).first()
    if reminder is None:
        raise ValidationError({"reminder": "Scheduled reminder was not found."})
    try:
        submitted_version = int(version)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"version": "Reload this schedule and try again."}) from exc
    if submitted_version != reminder.version:
        raise ValidationError(
            {"version": "This schedule changed in another tab. Reload and try again."}
        )
    reminder.active = False
    reminder.next_fire_at = None
    reminder.cancelled_at = now
    reminder.snoozed_until = None
    reminder.version += 1
    reminder.save(
        update_fields=[
            "active",
            "next_fire_at",
            "cancelled_at",
            "snoozed_until",
            "version",
            "updated_at",
        ]
    )
    _cancel_pending_schedule_events(reminder)
    return reminder


@transaction.atomic
def snooze_scheduled_reminder(*, user, reminder_id, version, choice, now=None):
    now = _canonical_instant(now or timezone.now())
    if choice not in SNOOZE_CHOICES:
        raise ValidationError({"choice": "Choose 15 minutes, 1 hour, or tomorrow."})
    reminder = ScheduledReminder.objects.select_for_update().filter(
        pk=reminder_id, user=user, active=True
    ).first()
    if reminder is None:
        raise ValidationError({"reminder": "Active scheduled reminder was not found."})
    try:
        submitted_version = int(version)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"version": "Reload this schedule and try again."}) from exc
    if submitted_version != reminder.version:
        raise ValidationError(
            {"version": "This schedule changed in another tab. Reload and try again."}
        )
    if choice == "15m":
        target = now + timedelta(minutes=15)
    elif choice == "1h":
        target = now + timedelta(hours=1)
    else:
        zone = _zone(reminder.timezone)
        tomorrow = now.astimezone(zone).date() + timedelta(days=1)
        target = _local_instant(tomorrow, reminder.anchor_time, zone)
    reminder.next_fire_at = _canonical_instant(target)
    reminder.snoozed_until = reminder.next_fire_at
    reminder.last_snoozed_at = now
    reminder.version += 1
    reminder.save(
        update_fields=[
            "next_fire_at",
            "snoozed_until",
            "last_snoozed_at",
            "version",
            "updated_at",
        ]
    )
    _cancel_pending_schedule_events(reminder)
    return reminder


def _retry_locked(operation):
    for attempt in range(8):
        try:
            return operation()
        except OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 7:
                raise
            time_module.sleep(0.02 * (attempt + 1))


def _claim_one_scheduled_reminder(reminder_id, now):
    with transaction.atomic():
        reminder = ScheduledReminder.objects.select_related(
            "user__profile", "project", "subproject"
        ).filter(pk=reminder_id).first()
        if reminder is None or not reminder.active or reminder.next_fire_at is None:
            return None
        old_next = _canonical_instant(reminder.next_fire_at)
        if old_next > now:
            return None
        next_fire = _next_reminder_slot(reminder, now)
        active = next_fire is not None
        claimed = ScheduledReminder.objects.filter(
            pk=reminder.pk,
            active=True,
            next_fire_at=reminder.next_fire_at,
            version=reminder.version,
        ).update(
            active=active,
            next_fire_at=next_fire,
            last_fired_at=old_next,
            snoozed_until=None,
            version=F("version") + 1,
        )
        if not claimed:
            return None
        preference = NotificationPreference.objects.filter(user_id=reminder.user_id).first()
        if preference is not None and not preference.scheduled_reminders_enabled:
            return None
        dedupe_key = f"scheduled:{reminder.pk}:{old_next.isoformat()}"
        event, created = NotificationEvent.objects.get_or_create(
            dedupe_key=dedupe_key,
            defaults={
                "event_type": "scheduled_reminder",
                "user_id": reminder.user_id,
                "scheduled_reminder_id": reminder.pk,
                "payload": _scheduled_payload(reminder, old_next),
                "scheduled_at": old_next,
            },
        )
        return event if created else None


def claim_due_scheduled_reminders(*, now=None, limit=100):
    now = _canonical_instant(now or timezone.now())
    limit = max(0, int(limit))
    if not limit:
        return []
    candidate_ids = (
        ScheduledReminder.objects.filter(
            active=True, next_fire_at__isnull=False, next_fire_at__lte=now
        )
        .order_by("next_fire_at", "pk")
        .values_list("pk", flat=True)
    )
    events = []
    for reminder_id in candidate_ids.iterator(chunk_size=200):
        if len(events) >= limit:
            break
        event = _retry_locked(lambda: _claim_one_scheduled_reminder(reminder_id, now))
        if event is not None:
            events.append(event)
    return events


def _commitment_name(commitment):
    target = getattr(commitment, commitment.aggregation_type, None)
    return getattr(target, "name", None) or "Commitment"


def _remaining_label(evaluation, remaining):
    if evaluation["commitment_type"] == "sessions":
        count = int(math.ceil(remaining))
        return f"{count} session{'s' if count != 1 else ''} remaining"
    minutes = int(math.ceil(remaining))
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m remaining"
    if hours:
        return f"{hours} hour{'s' if hours != 1 else ''} remaining"
    return f"{minutes} minute{'s' if minutes != 1 else ''} remaining"


def _deadline_day(deadline, zone):
    # Commitment period ends are exclusive.  The preceding local date is the
    # human deadline (a Monday 00:00 boundary therefore reads as Sunday).
    return (deadline.astimezone(zone) - timedelta(microseconds=1)).strftime("%A")


def _commitment_start_url(commitment):
    if commitment.aggregation_type == "project" and commitment.project_id:
        return f"{reverse('start_timer')}?{urlencode({'project_id': commitment.project_id})}"
    if commitment.aggregation_type == "subproject" and commitment.subproject_id:
        query = {
            "project_id": commitment.subproject.parent_project_id,
            "subproject_id": commitment.subproject_id,
        }
        return f"{reverse('start_timer')}?{urlencode(query)}"
    return reverse("update_commitment", args=[commitment.pk])


def _commitment_dedupe_key(commitment, evaluation):
    period_start = _canonical_instant(evaluation["period_start"])
    return (
        f"commitment:{commitment.pk}:{commitment.generation}:"
        f"{period_start.isoformat()}"
    )


def _commitment_event(commitment, occurrence, actionability, profile_zone):
    evaluation = actionability["evaluation"]
    start_url = _commitment_start_url(commitment)
    detail_url = reverse("update_commitment", args=[commitment.pk])
    name = _commitment_name(commitment)
    body = (
        f"{name}: {_remaining_label(evaluation, actionability['remaining'])}; "
        f"period ends {_deadline_day(actionability['deadline'], profile_zone)}."
    )
    period_start = _canonical_instant(evaluation["period_start"])
    dedupe_key = _commitment_dedupe_key(commitment, evaluation)
    payload = validate_notification_payload({
        "title": "Commitment needs a decision",
        "body": body,
        "url": start_url,
        "kind": "commitment_check",
        "commitment_id": commitment.pk,
        "scheduled_at": occurrence.isoformat(),
        "tag": f"commitment-{commitment.pk}-{commitment.generation}-{int(period_start.timestamp())}",
        "actions": [
            {"action": "start", "title": "Start", "url": start_url},
            {"action": "view", "title": "View commitment", "url": detail_url},
        ],
    })
    return NotificationEvent.objects.get_or_create(
        dedupe_key=dedupe_key,
        defaults={
            "event_type": "commitment_check",
            "user_id": commitment.user_id,
            "commitment_id": commitment.pk,
            "payload": payload,
            "scheduled_at": occurrence,
        },
    )


def _claim_one_commitment_preference(preference_id, now, event_limit):
    if event_limit <= 0:
        return []
    with transaction.atomic():
        preference = (
            NotificationPreference.objects.select_for_update()
            .select_related("user__profile")
            .filter(pk=preference_id)
            .first()
        )
        if (
            preference is None
            or not preference.commitment_checks_enabled
            or preference.next_commitment_check_at is None
            or preference.next_commitment_check_at > now
        ):
            return []
        old_next = preference.next_commitment_check_at
        zone = user_timezone(preference.user)
        occurrence = _latest_daily_slot(preference.commitment_check_time, zone, now)
        next_slot = _next_daily_slot(preference.commitment_check_time, zone, now)
        events = []
        commitments = Commitment.objects.filter(
            user_id=preference.user_id,
            active=True,
            notifications_enabled=True,
        ).select_related(
            "project", "subproject__parent_project", "context", "tag"
        ).order_by("pk")
        occurrence_fully_handled = True
        with timezone.override(zone):
            for commitment in commitments:
                actionability = get_commitment_actionability(commitment, occurrence)
                if not actionability["actionable"]:
                    continue

                dedupe_key = _commitment_dedupe_key(
                    commitment, actionability["evaluation"]
                )
                if NotificationEvent.objects.filter(dedupe_key=dedupe_key).exists():
                    continue
                if len(events) >= event_limit:
                    # Leave this preference on the same occurrence.  A later
                    # bounded pass resumes it and dedupe keys skip the events
                    # already materialized above.
                    occurrence_fully_handled = False
                    continue
                event, created = _commitment_event(
                    commitment, occurrence, actionability, zone
                )
                if created:
                    events.append(event)

        if occurrence_fully_handled:
            NotificationPreference.objects.filter(
                pk=preference.pk,
                commitment_checks_enabled=True,
                next_commitment_check_at=old_next,
                version=preference.version,
            ).update(
                next_commitment_check_at=next_slot,
                version=F("version") + 1,
            )
        return events


def claim_due_commitment_checks(*, now=None, limit=100):
    now = _canonical_instant(now or timezone.now())
    limit = max(0, int(limit))
    if not limit:
        return []
    candidate_ids = (
        NotificationPreference.objects.filter(
            commitment_checks_enabled=True,
            next_commitment_check_at__isnull=False,
            next_commitment_check_at__lte=now,
        )
        .order_by("next_commitment_check_at", "pk")
        .values_list("pk", flat=True)
    )
    events = []
    for preference_id in candidate_ids.iterator(chunk_size=200):
        if len(events) >= limit:
            break
        remaining = limit - len(events)
        events.extend(
            _retry_locked(
                lambda: _claim_one_commitment_preference(
                    preference_id, now, remaining
                )
            )
        )
    return events


def weekly_review_window(preference, occurrence):
    zone = user_timezone(preference.user)
    local_slot = occurrence.astimezone(zone)
    end_date = local_slot.date()
    start_date = end_date - timedelta(days=7)
    start = _local_instant(start_date, time.min, zone)
    end = _local_instant(end_date, time.min, zone)
    return start, end, zone


def _duration_label(minutes):
    total = max(0, int(round(minutes)))
    hours, minutes = divmod(total, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def weekly_review_summary(preference, occurrence):
    start, end, zone = weekly_review_window(preference, occurrence)
    with timezone.override(zone):
        sessions = summarize_completed_sessions(preference.user, start, end)
        commitments = weekly_commitment_score(preference.user, start, end)
    return {
        "window_start": start,
        "window_end": end,
        "timezone": zone.key,
        **sessions,
        **commitments,
    }


def _weekly_review_event(preference, occurrence, summary):
    project_count = summary["project_count"]
    eligible_count = summary["eligible_count"]
    body = (
        f"{_duration_label(summary['total_minutes'])} across {project_count} "
        f"project{'s' if project_count != 1 else ''}; "
        f"{summary['met_count']} of {eligible_count} commitments met."
    )
    week = summary["window_start"].astimezone(_zone(summary["timezone"])).date()
    review_url = f"{reverse('weekly_review')}?{urlencode({'week': week.isoformat()})}"
    # The reviewed local week is the durable identity.  Keep the key tied to
    # the user's local date rather than UTC bounds or timezone spelling, so a
    # profile-zone/DST change cannot create a second event for the same week.
    dedupe_key = f"weekly-review:{preference.user_id}:{week.isoformat()}"
    payload = validate_notification_payload({
        "title": "Your Autumn week",
        "body": body,
        "url": review_url,
        "kind": "weekly_review",
        "week_start": week.isoformat(),
        "scheduled_at": occurrence.isoformat(),
        "tag": f"weekly-review-{preference.user_id}-{week.isoformat()}",
        "actions": [
            {"action": "view", "title": "Open review", "url": review_url}
        ],
    })
    return NotificationEvent.objects.get_or_create(
        dedupe_key=dedupe_key,
        defaults={
            "event_type": "weekly_review",
            "user_id": preference.user_id,
            "payload": payload,
            "scheduled_at": occurrence,
        },
    )


def _claim_one_weekly_preference(preference_id, now):
    with transaction.atomic():
        preference = (
            NotificationPreference.objects.select_for_update()
            .select_related("user__profile")
            .filter(pk=preference_id)
            .first()
        )
        if (
            preference is None
            or not preference.weekly_review_enabled
            or preference.next_weekly_review_at is None
            or preference.next_weekly_review_at > now
        ):
            return []
        old_next = preference.next_weekly_review_at
        zone = user_timezone(preference.user)
        occurrence = _latest_weekly_slot(
            preference.weekly_review_weekday,
            preference.weekly_review_time,
            zone,
            now,
        )
        next_slot = _next_weekly_slot(
            preference.weekly_review_weekday,
            preference.weekly_review_time,
            zone,
            now,
        )
        summary = weekly_review_summary(preference, occurrence)
        event, created = _weekly_review_event(preference, occurrence, summary)
        claimed = NotificationPreference.objects.filter(
            pk=preference.pk,
            weekly_review_enabled=True,
            next_weekly_review_at=old_next,
            version=preference.version,
        ).update(next_weekly_review_at=next_slot, version=F("version") + 1)
        if not claimed:
            return []
        return [event] if created else []


def claim_due_weekly_reviews(*, now=None, limit=100):
    now = _canonical_instant(now or timezone.now())
    limit = max(0, int(limit))
    if not limit:
        return []
    candidate_ids = (
        NotificationPreference.objects.filter(
            weekly_review_enabled=True,
            next_weekly_review_at__isnull=False,
            next_weekly_review_at__lte=now,
        )
        .order_by("next_weekly_review_at", "pk")
        .values_list("pk", flat=True)
    )
    events = []
    for preference_id in candidate_ids.iterator(chunk_size=200):
        if len(events) >= limit:
            break
        events.extend(_retry_locked(lambda: _claim_one_weekly_preference(preference_id, now)))
    return events


def claim_due_proactive_notifications(*, now=None, limit=100):
    """Claim a fair, event-bounded mix of all proactive categories."""

    now = _canonical_instant(now or timezone.now())
    limit = max(0, int(limit))
    if not limit:
        return []

    # One event per category per round prevents a busy scheduled-reminder lane
    # from consuming the whole pass before commitment checks and reviews get a
    # turn.  Each category claimer is itself event-bounded, so no result is
    # created and then discarded at the global limit.
    claimers = (
        claim_due_scheduled_reminders,
        claim_due_commitment_checks,
        claim_due_weekly_reviews,
    )
    events = []
    while len(events) < limit:
        made_progress = False
        for claimer in claimers:
            if len(events) >= limit:
                break
            claimed = claimer(now=now, limit=1)
            if claimed:
                events.extend(claimed)
                made_progress = True
        if not made_progress:
            break
    return events
