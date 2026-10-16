from datetime import datetime, timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import QueryDict
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.api_v2.exceptions import V2APIView
from core.forms import NotificationPreferenceForm, ScheduledReminderForm
from core.models import Commitment, ScheduledReminder
from core.services.proactive_notifications import (
    cancel_scheduled_reminder,
    create_scheduled_reminder,
    ensure_notification_preferences,
    local_wall_to_utc,
    reschedule_notification_preferences,
    snooze_scheduled_reminder,
    update_scheduled_reminder,
    user_timezone,
    weekly_review_summary,
)


def _form_errors(form):
    return {
        field: [str(message) for message in messages]
        for field, messages in form.errors.items()
    }


def _django_error(exc):
    if hasattr(exc, "message_dict"):
        return {key: [str(value) for value in values] for key, values in exc.message_dict.items()}
    return {"non_field_errors": [str(exc)]}


class NotificationPreferenceSerializer(serializers.Serializer):
    scheduled_reminders_enabled = serializers.BooleanField()
    commitment_checks_enabled = serializers.BooleanField()
    weekly_review_enabled = serializers.BooleanField()
    commitment_check_time = serializers.TimeField()
    weekly_review_weekday = serializers.IntegerField(min_value=0, max_value=6)
    weekly_review_time = serializers.TimeField()
    next_commitment_check_at = serializers.DateTimeField(allow_null=True)
    next_weekly_review_at = serializers.DateTimeField(allow_null=True)
    version = serializers.IntegerField()


class NotificationPreferencePatchSerializer(serializers.Serializer):
    scheduled_reminders_enabled = serializers.BooleanField(required=False)
    commitment_checks_enabled = serializers.BooleanField(required=False)
    weekly_review_enabled = serializers.BooleanField(required=False)
    commitment_check_time = serializers.TimeField(required=False)
    weekly_review_weekday = serializers.IntegerField(required=False, min_value=0, max_value=6)
    weekly_review_time = serializers.TimeField(required=False)


class ScheduleWriteSerializer(serializers.Serializer):
    target = serializers.ChoiceField(choices=("project", "context", "tag"))
    project = serializers.IntegerField(required=False, allow_null=True)
    context = serializers.IntegerField(required=False, allow_null=True)
    tag = serializers.IntegerField(required=False, allow_null=True)
    subprojects = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list
    )
    local_date = serializers.DateField()
    local_time = serializers.TimeField()
    cadence = serializers.ChoiceField(choices=("once", "daily", "weekly"))
    message = serializers.CharField(required=False, allow_blank=True, max_length=240)
    version = serializers.IntegerField(required=False)


class SchedulePatchSerializer(ScheduleWriteSerializer):
    target = serializers.ChoiceField(choices=("project", "context", "tag"), required=False)
    local_date = serializers.DateField(required=False)
    local_time = serializers.TimeField(required=False)
    cadence = serializers.ChoiceField(choices=("once", "daily", "weekly"), required=False)
    subprojects = serializers.ListField(child=serializers.IntegerField(), required=False)
    version = serializers.IntegerField()


class ScheduleDeleteSerializer(serializers.Serializer):
    version = serializers.IntegerField()


class ScheduleNamedResourceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class ScheduleSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    target = serializers.CharField()
    target_resource = ScheduleNamedResourceSerializer()
    subprojects = ScheduleNamedResourceSerializer(many=True)
    message = serializers.CharField(allow_blank=True)
    cadence = serializers.CharField()
    timezone = serializers.CharField()
    local_date = serializers.DateField(source="anchor_date")
    local_time = serializers.TimeField(source="anchor_time")
    next_fire_at = serializers.DateTimeField(allow_null=True)
    snoozed_until = serializers.DateTimeField(allow_null=True)
    active = serializers.BooleanField()
    version = serializers.IntegerField()


class ScheduleListSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    schedules = ScheduleSerializer(many=True)
    upcoming = ScheduleSerializer(many=True)


class SnoozeRequestSerializer(serializers.Serializer):
    choice = serializers.ChoiceField(choices=("15m", "1h", "tomorrow"))
    version = serializers.IntegerField()


def _schedule_payload(schedule):
    target_name = next(name for name in schedule.TARGET_FIELDS if getattr(schedule, f"{name}_id"))
    target = getattr(schedule, target_name)
    return {
        "id": schedule.pk,
        "target": target_name,
        "target_resource": {"id": target.pk, "name": target.name},
        "subprojects": [
            {"id": subproject.pk, "name": subproject.name}
            for subproject in schedule.subprojects.all()
        ],
        "message": schedule.message,
        "cadence": schedule.cadence,
        "timezone": schedule.timezone,
        "local_date": schedule.anchor_date,
        "local_time": schedule.anchor_time,
        # Pre-schema names, kept so existing callers don't break.
        "anchor_date": schedule.anchor_date,
        "anchor_time": schedule.anchor_time,
        "next_fire_at": schedule.next_fire_at,
        "snoozed_until": schedule.snoozed_until,
        "active": schedule.active,
        "version": schedule.version,
    }


def _schedule_queryset(user):
    return ScheduledReminder.objects.filter(user=user, active=True).select_related(
        "project", "context", "tag"
    ).prefetch_related("subprojects")


def _form_data(data):
    query = QueryDict(mutable=True)
    for key, value in data.items():
        if key == "subprojects":
            query.setlist(key, [str(item) for item in value])
        elif value is not None:
            query[key] = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return query


def _validated_schedule_form(user, data):
    form = ScheduledReminderForm(_form_data(data), user=user)
    if not form.is_valid():
        raise ValidationError(_form_errors(form))
    return form


class NotificationPreferencesView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="notifications_preferences_retrieve", responses=NotificationPreferenceSerializer)
    def get(self, request):
        return Response(NotificationPreferenceSerializer(ensure_notification_preferences(request.user)).data)

    @extend_schema(
        operation_id="notifications_preferences_partial_update",
        request=NotificationPreferencePatchSerializer,
        responses=NotificationPreferenceSerializer,
    )
    def patch(self, request):
        serializer = NotificationPreferencePatchSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        preference = ensure_notification_preferences(request.user)
        merged = {
            field: serializer.validated_data.get(field, getattr(preference, field))
            for field in NotificationPreferenceForm.Meta.fields
        }
        form = NotificationPreferenceForm(merged, instance=preference, user=request.user)
        if not form.is_valid():
            raise ValidationError(_form_errors(form))
        try:
            preference = form.save(commit=False)
            preference.user = request.user
            reschedule_notification_preferences(preference)
        except DjangoValidationError as exc:
            raise ValidationError(_django_error(exc)) from exc
        return Response(NotificationPreferenceSerializer(preference).data)


class NotificationSchedulesView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="notifications_schedules_list", responses=ScheduleListSerializer)
    def get(self, request):
        schedules = list(_schedule_queryset(request.user))
        horizon = timezone.now() + timedelta(days=7)
        return Response(
            {
                "count": len(schedules),
                "schedules": [_schedule_payload(item) for item in schedules],
                "upcoming": [
                    _schedule_payload(item)
                    for item in schedules
                    if item.next_fire_at and item.next_fire_at <= horizon
                ],
            }
        )

    @extend_schema(
        operation_id="notifications_schedules_create",
        request=ScheduleWriteSerializer,
        responses={201: ScheduleSerializer},
    )
    def post(self, request):
        serializer = ScheduleWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        form = _validated_schedule_form(request.user, serializer.validated_data)
        try:
            reminder = create_scheduled_reminder(
                user=request.user,
                project=form.cleaned_data.get("project"),
                context=form.cleaned_data.get("context"),
                tag=form.cleaned_data.get("tag"),
                subprojects=form.cleaned_data.get("subprojects"),
                local_date=form.cleaned_data["local_date"],
                local_time=form.cleaned_data["local_time"],
                cadence=form.cleaned_data["cadence"],
                message=form.cleaned_data.get("message", ""),
            )
        except DjangoValidationError as exc:
            raise ValidationError(_django_error(exc)) from exc
        reminder = _schedule_queryset(request.user).get(pk=reminder.pk)
        return Response(_schedule_payload(reminder), status=status.HTTP_201_CREATED)


class NotificationScheduleDetailView(V2APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, request, schedule_id):
        reminder = _schedule_queryset(request.user).filter(pk=schedule_id).first()
        if reminder is None:
            raise NotFound("Scheduled reminder not found.")
        return reminder

    @extend_schema(
        operation_id="notifications_schedules_partial_update",
        request=SchedulePatchSerializer,
        responses=ScheduleSerializer,
    )
    def patch(self, request, schedule_id):
        reminder = self._get(request, schedule_id)
        serializer = SchedulePatchSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        current = {
            "target": "context" if reminder.context_id else "tag" if reminder.tag_id else "project",
            "project": reminder.project_id,
            "context": reminder.context_id,
            "tag": reminder.tag_id,
            "subprojects": list(reminder.subprojects.values_list("pk", flat=True)),
            "local_date": reminder.anchor_date,
            "local_time": reminder.anchor_time,
            "cadence": reminder.cadence,
            "message": reminder.message,
            "version": reminder.version,
        }
        current.update(serializer.validated_data)
        form = _validated_schedule_form(request.user, current)
        try:
            updated = update_scheduled_reminder(
                user=request.user,
                reminder_id=reminder.pk,
                version=form.cleaned_data.get("version"),
                project=form.cleaned_data.get("project"),
                context=form.cleaned_data.get("context"),
                tag=form.cleaned_data.get("tag"),
                subprojects=form.cleaned_data.get("subprojects"),
                local_date=form.cleaned_data["local_date"],
                local_time=form.cleaned_data["local_time"],
                cadence=form.cleaned_data["cadence"],
                message=form.cleaned_data.get("message", ""),
            )
        except (DjangoValidationError, ValueError) as exc:
            raise ValidationError(_django_error(exc)) from exc
        updated = _schedule_queryset(request.user).get(pk=updated.pk)
        return Response(_schedule_payload(updated))

    @extend_schema(
        operation_id="notifications_schedules_destroy",
        request=ScheduleDeleteSerializer,
        responses={204: OpenApiResponse(description="Schedule cancelled.")},
    )
    def delete(self, request, schedule_id):
        reminder = self._get(request, schedule_id)
        serializer = ScheduleDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            cancel_scheduled_reminder(
                user=request.user,
                reminder_id=reminder.pk,
                version=serializer.validated_data["version"],
            )
        except (DjangoValidationError, ValueError) as exc:
            raise ValidationError(_django_error(exc)) from exc
        return Response(status=status.HTTP_204_NO_CONTENT)


class NotificationScheduleSnoozeView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="notifications_schedules_snooze_create",
        request=SnoozeRequestSerializer,
        responses=ScheduleSerializer,
    )
    def post(self, request, schedule_id):
        if not _schedule_queryset(request.user).filter(pk=schedule_id).exists():
            raise NotFound("Scheduled reminder not found.")
        serializer = SnoozeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            reminder = snooze_scheduled_reminder(
                user=request.user,
                reminder_id=schedule_id,
                version=serializer.validated_data["version"],
                choice=serializer.validated_data["choice"],
            )
        except ScheduledReminder.DoesNotExist as exc:
            raise NotFound("Scheduled reminder not found.") from exc
        except (DjangoValidationError, TypeError, ValueError) as exc:
            raise ValidationError(_django_error(exc)) from exc
        reminder = _schedule_queryset(request.user).get(pk=reminder.pk)
        return Response(_schedule_payload(reminder))


class WeeklyProjectSerializer(serializers.Serializer):
    project_id = serializers.IntegerField()
    project_name = serializers.CharField()
    total_minutes = serializers.FloatField()
    session_count = serializers.IntegerField()


class WeeklyPeriodSerializer(serializers.Serializer):
    actual = serializers.FloatField()
    target = serializers.FloatField()
    balance = serializers.FloatField()
    banking_enabled = serializers.BooleanField()
    met = serializers.BooleanField()
    saved_by_bank = serializers.BooleanField()
    period_start = serializers.DateTimeField()
    period_end = serializers.DateTimeField()


class WeeklyCommitmentSerializer(serializers.Serializer):
    commitment_id = serializers.IntegerField()
    target_name = serializers.CharField()
    period_count = serializers.IntegerField()
    met_period_count = serializers.IntegerField()
    met = serializers.BooleanField()
    periods = WeeklyPeriodSerializer(many=True)


class WeeklyReviewSerializer(serializers.Serializer):
    window_start = serializers.DateTimeField()
    window_end = serializers.DateTimeField()
    timezone = serializers.CharField()
    week_start = serializers.DateField()
    week_end = serializers.DateField()
    total_minutes = serializers.FloatField()
    duration_label = serializers.CharField()
    project_count = serializers.IntegerField()
    session_count = serializers.IntegerField()
    per_project = WeeklyProjectSerializer(many=True)
    met_count = serializers.IntegerField()
    eligible_count = serializers.IntegerField()
    details = WeeklyCommitmentSerializer(many=True)


class WeeklyReviewQuerySerializer(serializers.Serializer):
    week = serializers.DateField(
        required=False,
        help_text=(
            "First local date of the seven reviewed (the weekly review "
            "notification links its own). Defaults to the seven days ending yesterday."
        ),
    )


class WeeklyReviewView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="reports_weekly_review_retrieve",
        parameters=[WeeklyReviewQuerySerializer],
        responses=WeeklyReviewSerializer,
    )
    def get(self, request):
        query = WeeklyReviewQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        preference = ensure_notification_preferences(request.user)
        zone = user_timezone(request.user)
        # A review covers the seven local dates before its slot, so a chosen
        # start date gets a slot seven days later; DST is resolved by the same
        # helper the scheduler uses.
        selected = query.validated_data.get("week")
        if selected is None:
            occurrence = timezone.now()
        else:
            occurrence = local_wall_to_utc(
                datetime.combine(selected + timedelta(days=7), preference.weekly_review_time),
                zone.key,
                strict=False,
            )
        summary = weekly_review_summary(preference, occurrence)
        week_start = summary["window_start"].astimezone(zone).date()
        commitments = {
            item.pk: item
            for item in Commitment.objects.filter(
                user=request.user,
                pk__in=[detail["commitment_id"] for detail in summary["details"]],
            )
        }
        details = [
            {**detail, "target_name": commitments[detail["commitment_id"]].target_name}
            for detail in summary["details"]
        ]
        total = max(0, int(round(summary["total_minutes"] or 0)))
        hours, minutes = divmod(total, 60)
        duration_label = f"{hours}h {minutes}m" if hours and minutes else f"{hours}h" if hours else f"{minutes}m"
        return Response(
            {
                **summary,
                "week_start": week_start,
                "week_end": week_start + timedelta(days=6),
                "duration_label": duration_label,
                "details": details,
            }
        )
