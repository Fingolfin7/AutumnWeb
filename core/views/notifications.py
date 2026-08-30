"""Authenticated pages for intentional, user-planned notifications."""

from __future__ import annotations

from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.forms import (
    NOTIFICATION_WEEKDAY_CHOICES,
    NotificationPreferenceForm,
    ScheduledReminderForm,
)
from core.models import Commitment, NotificationPreference, ScheduledReminder
from core.services.proactive_notifications import (
    cancel_scheduled_reminder as cancel_schedule,
    create_scheduled_reminder,
    ensure_notification_preferences,
    local_wall_to_utc,
    reschedule_notification_preferences,
    snooze_scheduled_reminder as snooze_schedule,
    update_scheduled_reminder,
    user_timezone,
    weekly_review_summary,
)


def _validation_text(error):
    if hasattr(error, "message_dict"):
        return " ".join(
            str(message)
            for messages_for_field in error.message_dict.values()
            for message in messages_for_field
        )
    return str(error) or "Please check the notification details."


def _notification_context(request, *, schedule_form=None, preference_form=None, editing=None):
    preference = ensure_notification_preferences(request.user)
    schedules = list(ScheduledReminder.objects.filter(
        user=request.user, active=True
    ).select_related("project", "subproject"))
    horizon = timezone.now() + timedelta(days=7)
    return {
        "title": "How Autumn interrupts you",
        "preference": preference,
        "preference_form": preference_form or NotificationPreferenceForm(
            instance=preference, user=request.user
        ),
        "schedule_form": schedule_form or ScheduledReminderForm(user=request.user),
        "schedules": schedules,
        "upcoming_schedules": [item for item in schedules if item.next_fire_at and item.next_fire_at <= horizon],
        "editing_schedule": editing,
        "weekly_weekday_label": dict(NOTIFICATION_WEEKDAY_CHOICES).get(
            preference.weekly_review_weekday, "Monday"
        ),
    }


@login_required
def notifications(request):
    """Settings and the user's active schedule rail."""

    preference = ensure_notification_preferences(request.user)
    action = request.POST.get("action", "") if request.method == "POST" else ""
    if not action:
        if request.method == "POST" and "project" in request.POST:
            action = "create_schedule"
        elif request.method == "POST":
            action = "save_preferences"

    if request.method == "POST" and action == "save_preferences":
        form = NotificationPreferenceForm(
            request.POST, instance=preference, user=request.user
        )
        if form.is_valid():
            try:
                preference = form.save(commit=False)
                preference.user = request.user
                reschedule_notification_preferences(preference)
            except ValidationError as error:
                form.add_error(None, _validation_text(error))
            else:
                messages.success(request, "Notification settings saved.")
                return redirect("notifications")
        return render(
            request,
            "core/notifications.html",
            _notification_context(request, preference_form=form),
        )

    if request.method == "POST" and action == "create_schedule":
        form = ScheduledReminderForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                create_scheduled_reminder(
                    user=request.user,
                    project=form.cleaned_data["project"],
                    subproject=form.cleaned_data.get("subproject"),
                    local_date=form.cleaned_data["local_date"],
                    local_time=form.cleaned_data["local_time"],
                    cadence=form.cleaned_data["cadence"],
                    message=form.cleaned_data.get("message", ""),
                )
            except ValidationError as error:
                form.add_error(None, _validation_text(error))
            else:
                messages.success(request, "Schedule added.")
                return redirect("notifications")
        return render(
            request,
            "core/notifications.html",
            _notification_context(request, schedule_form=form),
        )

    return render(request, "core/notifications.html", _notification_context(request))


@login_required
def edit_scheduled_reminder(request, reminder_id):
    reminder = get_object_or_404(
        ScheduledReminder.objects.select_related("project", "subproject"),
        pk=reminder_id,
        user=request.user,
        active=True,
    )
    if request.method == "POST":
        form = ScheduledReminderForm(request.POST, user=request.user, instance=reminder)
        if form.is_valid():
            try:
                update_scheduled_reminder(
                    user=request.user,
                    reminder_id=reminder.pk,
                    version=form.cleaned_data.get("version"),
                    project=form.cleaned_data["project"],
                    subproject=form.cleaned_data.get("subproject"),
                    local_date=form.cleaned_data["local_date"],
                    local_time=form.cleaned_data["local_time"],
                    cadence=form.cleaned_data["cadence"],
                    message=form.cleaned_data.get("message", ""),
                )
            except (ValidationError, ValueError) as error:
                form.add_error(None, _validation_text(error))
            else:
                messages.success(request, "Schedule updated.")
                return redirect("notifications")
        return render(
            request,
            "core/notifications.html",
            _notification_context(request, schedule_form=form, editing=reminder),
        )
    form = ScheduledReminderForm(user=request.user, instance=reminder)
    return render(
        request,
        "core/notifications.html",
        _notification_context(request, schedule_form=form, editing=reminder),
    )


@login_required
def snooze_scheduled_reminder(request, reminder_id):
    reminder = get_object_or_404(ScheduledReminder, pk=reminder_id, user=request.user)
    if request.method == "GET":
        return render(
            request,
            "core/snooze_scheduled_reminder.html",
            {
                "title": "Snooze scheduled reminder",
                "reminder": reminder,
                "is_cancel": False,
                "cancel_url": "notifications",
            },
        )
    if request.method != "POST":
        return redirect("notifications")
    try:
        snooze_schedule(
            user=request.user,
            reminder_id=reminder.pk,
            version=request.POST.get("version"),
            choice=request.POST.get("choice", ""),
        )
    except (ValidationError, TypeError, ValueError) as error:
        messages.error(request, _validation_text(error))
        return redirect("notifications")
    messages.success(request, "Reminder snoozed.")
    return redirect("notifications")


@login_required
def cancel_scheduled_reminder(request, reminder_id):
    reminder = get_object_or_404(ScheduledReminder, pk=reminder_id, user=request.user)
    if request.method == "GET":
        return render(
            request,
            "core/snooze_scheduled_reminder.html",
            {
                "title": "Cancel scheduled reminder",
                "reminder": reminder,
                "is_cancel": True,
                "cancel_url": "notifications",
            },
        )
    if request.method != "POST":
        return redirect("notifications")
    try:
        cancel_schedule(
            user=request.user,
            reminder_id=reminder.pk,
            version=request.POST.get("version"),
        )
    except (ValidationError, TypeError, ValueError) as error:
        messages.error(request, _validation_text(error))
        return redirect("notifications")
    messages.success(request, "Schedule cancelled.")
    return redirect("notifications")


@login_required
def weekly_review(request):
    preference = ensure_notification_preferences(request.user)
    zone = user_timezone(request.user)
    week_value = (request.GET.get("week") or "").strip()
    occurrence = timezone.now()
    selected_week = None
    if week_value:
        try:
            selected_week = datetime.strptime(week_value, "%Y-%m-%d").date()
        except ValueError:
            selected_week = None
        if selected_week is not None:
            # The summary service defines a review by the seven local dates
            # immediately before its slot.  Put the requested week before a
            # deterministic local midnight slot, so DST is resolved by the
            # same helper used by the scheduler.
            end_date = selected_week + timedelta(days=7)
            occurrence = local_wall_to_utc(
                datetime.combine(end_date, preference.weekly_review_time),
                zone.key,
                strict=False,
            )
    summary = weekly_review_summary(preference, occurrence)
    commitment_ids = [item["commitment_id"] for item in summary.get("details", [])]
    commitments = {
        commitment.pk: commitment
        for commitment in Commitment.objects.filter(
            user=request.user, pk__in=commitment_ids
        ).select_related("project", "subproject", "context", "tag")
    }
    commitment_details = []
    for item in summary.get("details", []):
        item = dict(item)
        item["commitment"] = commitments.get(item["commitment_id"])
        commitment_details.append(item)
    summary["details"] = commitment_details
    summary["duration_label"] = _duration_label(summary.get("total_minutes", 0))
    summary["week_start_label"] = summary["window_start"].astimezone(zone).date()
    summary["week_end_label"] = (
        summary["window_end"].astimezone(zone).date() - timedelta(days=1)
    )
    return render(
        request,
        "core/weekly_review.html",
        {"title": "Your Autumn week", "summary": summary},
    )


def _duration_label(minutes):
    total = max(0, int(round(minutes or 0)))
    hours, remainder = divmod(total, 60)
    if hours and remainder:
        return f"{hours}h {remainder}m"
    if hours:
        return f"{hours}h"
    return f"{remainder}m"
