from datetime import datetime, time, timezone as dt_tz
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
import logging

logger = logging.getLogger('models')


status_choices = (
    ('active', 'Active'),
    ('paused', 'Paused'),
    ('complete', 'Complete'),
    ('archived', 'Archived')
)


User._meta.get_field('email')._unique = True  # make email field unique


class Context(models.Model):
    """
    Hard scope for projects (e.g. Work, Personal, Study).
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='contexts')
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)

    class Meta:
        verbose_name = 'Context'
        verbose_name_plural = 'Contexts'
        unique_together = ('user', 'name')
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.user.username})"


class Tag(models.Model):
    """
    Soft descriptor for projects (many-to-many).
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tags')
    name = models.CharField(max_length=100)
    color = models.CharField(max_length=20, null=True, blank=True)

    class Meta:
        verbose_name = 'Tag'
        verbose_name_plural = 'Tags'
        unique_together = ('user', 'name')
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.user.username})"


# model to track the projects that a user is working on
class Projects(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    start_date = models.DateTimeField(default=timezone.now)
    last_updated = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=25, choices=status_choices, default='active')

    # Dropped in S12: totals are always derived (core/totals.py). The legacy
    # creation kwarg is accepted and ignored.
    def __init__(self, *args, **kwargs):
        kwargs.pop("total_time", None)
        super().__init__(*args, **kwargs)
    description = models.TextField(null=True, blank=True)
    context = models.ForeignKey(
        Context,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='projects'
    )
    tags = models.ManyToManyField(
        Tag,
        blank=True,
        related_name='projects'
    )

    class Meta:
        verbose_name_plural = 'Projects'
        ordering = ['name']
        unique_together = ('user', 'name')

    def __str__(self):
        return f"{self.name} ({self.user.username})"

    @property
    def get_start(self):
        return datetime.combine(self.start_date, time())

    @property
    def get_end(self):
        return datetime.combine(self.last_updated, time())

    def save(self, *args, **kwargs):
        """Ensure projects always have a context.

        If none is provided, assign the per-user 'General' context.
        This makes behavior consistent for imports/legacy data and any code path that bypasses forms.
        """
        if self.context_id is None and self.user_id is not None:
            general, _ = Context.objects.get_or_create(
                user=self.user,
                name='General',
                defaults={'description': 'Default context'},
            )
            self.context = general
        super().save(*args, **kwargs)


class SubProjects(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    start_date = models.DateTimeField(default=timezone.now)
    last_updated = models.DateTimeField(default=timezone.now)
    description = models.TextField(null=True, blank=True)
    parent_project = models.ForeignKey(Projects, on_delete=models.CASCADE, related_name='subprojects')

    # Dropped in S12: totals are always derived (core/totals.py).
    def __init__(self, *args, **kwargs):
        kwargs.pop("total_time", None)
        super().__init__(*args, **kwargs)

    class Meta:
        verbose_name_plural = 'SubProjects'
        unique_together = ('name', 'parent_project')

    def __str__(self):
        return f"{self.name} ({self.parent_project.name}) ({self.user.username})"

    @property
    def get_start(self):
        return datetime.combine(self.start_date, time())

    @property
    def get_end(self):
        return datetime.combine(self.last_updated, time())

    # when a subproject is deleted, remove it from all its sessions
    def delete(self, *args, **kwargs):
        for session in self.sessions.all():
            session.subprojects.remove(self)
            session.save()
        super(SubProjects, self).delete(*args, **kwargs)


class SessionSubproject(models.Model):
    session = models.ForeignKey(
        'Sessions',
        on_delete=models.CASCADE,
        db_column='sessions_id',
        related_name='subproject_links',
        # The (session, subproject) unique constraint's prefix covers session
        # lookups; the PG benchmark showed the standalone index redundant.
        db_index=False,
    )
    subproject = models.ForeignKey(
        'SubProjects',
        on_delete=models.CASCADE,
        db_column='subprojects_id',
        related_name='session_links',
    )
    allocation_bp = models.IntegerField(default=10000, db_default=10000)

    class Meta:
        db_table = 'core_sessions_subprojects'
        unique_together = (('session', 'subproject'),)
        constraints = [
            models.CheckConstraint(
                condition=models.Q(allocation_bp__gte=1) & models.Q(allocation_bp__lte=10000),
                name='session_subproject_allocation_bp_range',
            ),
        ]


class Sessions(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    uuid = models.UUIDField(blank=True, editable=False, default=uuid.uuid4)
    project = models.ForeignKey(Projects, on_delete=models.CASCADE, related_name='sessions')
    subprojects = models.ManyToManyField(
        SubProjects,
        related_name='sessions',
        through='SessionSubproject',
        through_fields=('session', 'subproject'),
    )
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)
    auto_stop_at = models.DateTimeField(null=True, blank=True)
    notify_on_auto_stop = models.BooleanField(default=False, db_default=False)
    note = models.TextField(null=True, blank=True)
    version = models.IntegerField(default=1, db_default=1)

    # Dropped in S12: is_active and crosses_dst_transition became derived
    # properties (below). Legacy creation kwargs are accepted and ignored so
    # long-standing call sites keep working.
    _LEGACY_INIT_KWARGS = ("is_active", "crosses_dst_transition")

    def __init__(self, *args, **kwargs):
        for legacy in self._LEGACY_INIT_KWARGS:
            kwargs.pop(legacy, None)
        super().__init__(*args, **kwargs)

    class Meta:
        verbose_name_plural = 'Sessions'
        ordering = ['-end_time']

        indexes = [
            # (user, project) dropped after the PG benchmark: the S5
            # (user, end_time) indexes cover the hot paths within ~0.5ms.
            models.Index(
                fields=['user', 'start_time', 'id'],
                name='sess_active_user_start_idx',
                condition=models.Q(end_time__isnull=True),
            ),
            models.Index(
                fields=['user', 'auto_stop_at', 'id'],
                name='sess_autostop_partial_idx',
                condition=models.Q(
                    end_time__isnull=True,
                    auto_stop_at__isnull=False,
                ),
            ),
            models.Index(
                fields=['user', 'end_time', 'id'],
                name='sess_completed_user_end_idx',
            ),
            models.Index(
                fields=['user', 'project', 'end_time', 'id'],
                name='sess_completed_proj_end_idx',
            ),
        ]

        constraints = [
            models.UniqueConstraint(
                fields=['user', 'uuid'], name='unique_session_uuid_per_user'
            ),
        ]

    def __str__(self):
        sub_list = [sub.name for sub in self.subprojects.all()]
        return f"{self.project.name} {sub_list} - {self.start_time} ({self.user.username})"

    def clean(self):
        """
        Ensure end_time is not earlier than start_time.
        """
        super().clean()
        if self.start_time and self.end_time and self.end_time < self.start_time:
            raise ValidationError({"end_time": "End time cannot be earlier than start time."})
        if self.start_time and self.auto_stop_at and self.auto_stop_at <= self.start_time:
            raise ValidationError({"auto_stop_at": "Auto-stop time must be after start time."})

    @property
    def get_start(self):
        return self.start_time

    @property
    def get_end(self):
        return self.end_time

    @property
    def duration(self):
        """
        Return the duration of the session in minutes or None if the session is still active
        :return:
        """
        if self.end_time is None and not self.is_active:
            return None
        elif self.is_active and not self.end_time:
            start_time = self._ensure_aware(self.start_time)
            if not start_time:
                return None
            return round(
                (
                    timezone.now().astimezone(dt_tz.utc)
                    - start_time.astimezone(dt_tz.utc)
                ).total_seconds()
                / 60.0,
                4,
            )
        else:
            start_time = self._ensure_aware(self.start_time)
            end_time = self._ensure_aware(self.end_time)
            if not start_time or not end_time:
                return None
            # Measure elapsed time by absolute instant to avoid DST wall-clock artifacts.
            return round(
                (
                    end_time.astimezone(dt_tz.utc)
                    - start_time.astimezone(dt_tz.utc)
                ).total_seconds()
                / 60.0,
                4,
            )

    @staticmethod
    def _ensure_aware(dt: datetime | None) -> datetime | None:
        if dt is None:
            return None
        if timezone.is_naive(dt):
            return timezone.make_aware(dt, timezone.get_default_timezone())
        return dt

    @classmethod
    def _compute_crosses_dst_transition(
        cls, start_time: datetime | None, end_time: datetime | None
    ) -> bool:
        start_aware = cls._ensure_aware(start_time)
        end_aware = cls._ensure_aware(end_time)
        if not start_aware or not end_aware:
            return False

        default_tz = timezone.get_default_timezone()
        start_local = timezone.localtime(start_aware, default_tz)
        end_local = timezone.localtime(end_aware, default_tz)
        return start_local.utcoffset() != end_local.utcoffset()

    @property
    def is_active(self):
        """Derived timer state: a session is active until it has an end."""
        return self.end_time is None

    @property
    def crosses_dst_transition(self):
        return self._compute_crosses_dst_transition(self.start_time, self.end_time)


class PushSubscription(models.Model):
    """A browser push subscription owned by one account.

    Endpoints are globally unique because a browser endpoint must never be
    allowed to receive two users' notifications.  The subscribe endpoint can
    transfer an existing endpoint to the currently authenticated user.
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="push_subscriptions"
    )
    endpoint = models.URLField(max_length=2048, unique=True)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    expiration_time = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True, db_default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    disabled_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="", db_default="")

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["user", "active", "id"], name="pushsub_user_active_idx"),
        ]


class TimerReminder(models.Model):
    """One notification schedule attached to an active timer."""

    MODE_CHOICES = (
        ("after", "Once after"),
        ("at", "At"),
        ("interval", "Every"),
    )

    session = models.ForeignKey(
        Sessions, on_delete=models.CASCADE, related_name="reminders"
    )
    mode = models.CharField(max_length=16, choices=MODE_CHOICES)
    next_fire_at = models.DateTimeField(null=True, blank=True)
    interval_seconds = models.PositiveIntegerField(null=True, blank=True)
    message = models.TextField(blank=True, default="", db_default="")
    active = models.BooleanField(default=True, db_default=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    last_fired_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["next_fire_at", "id"]
        indexes = [
            models.Index(
                fields=["active", "next_fire_at", "id"],
                name="timerrem_due_idx",
            ),
            models.Index(fields=["session", "active", "id"], name="timerrem_session_active_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(mode__in=("after", "at", "interval")),
                name="timerrem_mode_valid",
            ),
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(mode="interval")
                        & models.Q(interval_seconds__isnull=False)
                        & models.Q(interval_seconds__gt=0)
                    )
                    | (
                        ~models.Q(mode="interval")
                        & models.Q(interval_seconds__isnull=True)
                    )
                ),
                name="timerrem_interval_seconds_valid",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(active=True, next_fire_at__isnull=True)
                ),
                name="timerrem_active_next_fire_valid",
            ),
        ]

    def clean(self):
        super().clean()
        if self.mode not in {choice[0] for choice in self.MODE_CHOICES}:
            raise ValidationError({"mode": "Unknown reminder mode."})
        if self.active and self.next_fire_at is None:
            raise ValidationError({"next_fire_at": "Active reminders need a next fire time."})
        if self.mode == "interval" and (
            self.interval_seconds is None or self.interval_seconds <= 0
        ):
            raise ValidationError(
                {"interval_seconds": "Interval reminders need a positive interval."}
            )
        if self.mode != "interval" and self.interval_seconds is not None:
            raise ValidationError(
                {"interval_seconds": "Only interval reminders have an interval."}
            )


class NotificationPreference(models.Model):
    """Per-user switches and local-time slots for proactive notifications.

    The ``next_*`` columns deliberately store instants rather than local
    datetimes.  Dispatchers can therefore claim due work with a portable
    compare-and-set update while the configured wall-clock values remain
    stable across timezone and DST changes.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    scheduled_reminders_enabled = models.BooleanField(
        default=True,
        db_default=True,
    )
    commitment_checks_enabled = models.BooleanField(
        default=False,
        db_default=False,
    )
    weekly_review_enabled = models.BooleanField(
        default=False,
        db_default=False,
    )
    # These two values are interpreted in the user's profile timezone.  The
    # commitment slot is intentionally limited to the final daily action
    # window; see clean() and the matching database check below.
    commitment_check_time = models.TimeField(
        default=time(hour=18),
        db_default=time(hour=18),
    )
    weekly_review_weekday = models.PositiveSmallIntegerField(
        default=0,
        db_default=0,
    )
    weekly_review_time = models.TimeField(
        default=time(hour=9),
        db_default=time(hour=9),
    )
    next_commitment_check_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )
    next_weekly_review_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )
    version = models.PositiveIntegerField(default=1, db_default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user_id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(commitment_check_time__gte=time(hour=18))
                    & models.Q(commitment_check_time__lte=time(hour=23, minute=59, second=59))
                ),
                name="notify_pref_commitment_time_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(weekly_review_weekday__gte=0)
                & models.Q(weekly_review_weekday__lte=6),
                name="notify_pref_weekday_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="notify_pref_version_positive",
            ),
        ]

    def __str__(self):
        return f"Notification preferences ({self.user.username})"

    def clean(self):
        super().clean()
        errors = {}

        if self.commitment_check_time is not None:
            earliest = time(hour=18)
            latest = time(hour=23, minute=59, second=59)
            if not earliest <= self.commitment_check_time <= latest:
                errors["commitment_check_time"] = (
                    "Commitment checks must be scheduled from 18:00 through 23:59."
                )

        if self.weekly_review_weekday is not None and not 0 <= self.weekly_review_weekday <= 6:
            errors["weekly_review_weekday"] = "Weekday must be between Monday (0) and Sunday (6)."

        for field_name in ("next_commitment_check_at", "next_weekly_review_at"):
            instant = getattr(self, field_name)
            if instant is not None and timezone.is_naive(instant):
                errors[field_name] = "The next notification instant must be timezone-aware."

        if errors:
            raise ValidationError(errors)


class ScheduledReminder(models.Model):
    """A user-owned, project-oriented reminder schedule.

    ``anchor_date`` and ``anchor_time`` are local wall-clock values in
    ``timezone``.  ``next_fire_at`` is their computed UTC instant and is the
    value the dispatcher claims.  A one-shot schedule becomes inactive after
    firing; ``cancelled_at`` distinguishes an explicit cancellation from a
    naturally completed one-shot schedule.
    """

    CADENCE_CHOICES = (
        ("once", "Once"),
        ("daily", "Daily"),
        ("weekly", "Weekly"),
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="scheduled_reminders",
    )
    project = models.ForeignKey(
        Projects,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="scheduled_reminders",
    )
    context = models.ForeignKey(
        Context,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="scheduled_reminders",
    )
    tag = models.ForeignKey(
        Tag,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="scheduled_reminders",
    )
    subprojects = models.ManyToManyField(
        SubProjects,
        blank=True,
        related_name="scheduled_reminders",
    )
    message = models.TextField(blank=True, default="", db_default="")
    cadence = models.CharField(max_length=10, choices=CADENCE_CHOICES)
    # Always capture the profile timezone used to interpret the local anchor;
    # callers must copy it explicitly so an account's timezone is never
    # silently replaced by a deployment-wide default.
    timezone = models.CharField(max_length=64)
    anchor_date = models.DateField()
    anchor_time = models.TimeField()
    next_fire_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True, db_default=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    last_fired_at = models.DateTimeField(null=True, blank=True)
    snoozed_until = models.DateTimeField(null=True, blank=True)
    last_snoozed_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1, db_default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["next_fire_at", "id"]
        indexes = [
            models.Index(
                fields=["active", "next_fire_at", "id"],
                name="schedrem_due_idx",
            ),
            models.Index(
                fields=["user", "active", "id"],
                name="schedrem_user_active_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cadence__in=("once", "daily", "weekly")),
                name="schedrem_cadence_valid",
            ),
            models.CheckConstraint(
                condition=~models.Q(active=True, next_fire_at__isnull=True),
                name="schedrem_active_next_fire_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="schedrem_version_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        project__isnull=False, context__isnull=True, tag__isnull=True
                    )
                    | models.Q(
                        project__isnull=True, context__isnull=False, tag__isnull=True
                    )
                    | models.Q(
                        project__isnull=True, context__isnull=True, tag__isnull=False
                    )
                ),
                name="schedrem_target_exactly_one",
            ),
        ]

    # Ordered so ``target_name`` and validation always agree on which single
    # relation carries the schedule's meaning.
    TARGET_FIELDS = ("project", "context", "tag")

    @property
    def target(self):
        """The single project, context, or tag this schedule points at."""

        for field_name in self.TARGET_FIELDS:
            if getattr(self, f"{field_name}_id"):
                return getattr(self, field_name)
        return None

    @property
    def target_name(self):
        """The human label of whichever single target this schedule holds."""

        return getattr(self.target, "name", None) or "Reminder"

    def __str__(self):
        return f"{self.target_name} reminder ({self.cadence})"

    def clean(self):
        super().clean()
        errors = {}

        if self.cadence not in {choice[0] for choice in self.CADENCE_CHOICES}:
            errors["cadence"] = "Unknown reminder cadence."

        chosen = [
            field_name
            for field_name in self.TARGET_FIELDS
            if getattr(self, f"{field_name}_id")
        ]
        if len(chosen) != 1:
            errors["project"] = "Choose a project, context, or tag."

        if self.user_id:
            for field_name in chosen:
                if getattr(self, field_name).user_id != self.user_id:
                    errors[field_name] = (
                        f"Reminder {field_name} must belong to the same user."
                    )

        if self.project_id and self.project.status not in {"active", "paused"}:
            errors["project"] = "Reminders can only target active or paused projects."

        if self.timezone:
            try:
                ZoneInfo(self.timezone)
            except (ZoneInfoNotFoundError, ValueError):
                errors["timezone"] = "Enter a valid IANA timezone."

        if self.active:
            if self.next_fire_at is None:
                errors["next_fire_at"] = "Active reminders need a next fire time."
            elif timezone.is_naive(self.next_fire_at):
                errors["next_fire_at"] = "The next fire instant must be timezone-aware."
            if self.cancelled_at is not None:
                errors["cancelled_at"] = "An active reminder cannot be cancelled."

        for field_name in ("cancelled_at", "last_fired_at", "snoozed_until", "last_snoozed_at"):
            instant = getattr(self, field_name)
            if instant is not None and timezone.is_naive(instant):
                errors[field_name] = "Reminder instants must be timezone-aware."

        if errors:
            raise ValidationError(errors)


class NotificationEvent(models.Model):
    """A durable, deduplicated notification waiting for delivery."""

    EVENT_TYPES = (
        ("reminder", "Timer reminder"),
        ("auto_stop", "Auto-stop"),
        ("scheduled_reminder", "Scheduled reminder"),
        ("commitment_check", "Commitment check"),
        ("weekly_review", "Weekly review"),
    )
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("delivered", "Delivered"),
        ("unavailable", "Unavailable"),
        ("failed", "Failed"),
        ("cancelled", "Cancelled"),
    )

    dedupe_key = models.CharField(max_length=255, unique=True)
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="notification_events"
    )
    session = models.ForeignKey(
        Sessions,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notification_events",
    )
    reminder = models.ForeignKey(
        TimerReminder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notification_events",
    )
    scheduled_reminder = models.ForeignKey(
        "ScheduledReminder",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notification_events",
    )
    commitment = models.ForeignKey(
        "Commitment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notification_events",
    )
    # A callable is valid as the Python default but cannot be serialized into
    # a database-level default on SQLite/PostgreSQL.
    payload = models.JSONField(default=dict)
    scheduled_at = models.DateTimeField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    attempts = models.PositiveIntegerField(default=0, db_default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="", db_default="")
    last_error_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["scheduled_at", "id"]
        indexes = [
            models.Index(fields=["status", "next_attempt_at", "id"], name="notifyevent_due_idx"),
            models.Index(fields=["user", "scheduled_at", "id"], name="notifyevent_user_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    event_type__in=(
                        "reminder",
                        "auto_stop",
                        "scheduled_reminder",
                        "commitment_check",
                        "weekly_review",
                    )
                ),
                name="notifyevent_type_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=(
                        "pending",
                        "processing",
                        "delivered",
                        "unavailable",
                        "failed",
                        "cancelled",
                    )
                ),
                name="notifyevent_status_valid",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.scheduled_reminder_id and self.scheduled_reminder.user_id != self.user_id:
            errors["scheduled_reminder"] = (
                "Scheduled reminder source must belong to the event user."
            )
        if self.commitment_id and self.commitment.user_id != self.user_id:
            errors["commitment"] = "Commitment source must belong to the event user."
        if errors:
            raise ValidationError(errors)


class NotificationDelivery(models.Model):
    """Per-event/per-browser delivery state used for retry-safe fan-out."""

    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("delivered", "Delivered"),
        ("expired", "Expired"),
        ("unavailable", "Unavailable"),
        ("failed", "Failed"),
    )

    event = models.ForeignKey(
        NotificationEvent, on_delete=models.CASCADE, related_name="deliveries"
    )
    subscription = models.ForeignKey(
        PushSubscription, on_delete=models.CASCADE, related_name="deliveries"
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    attempts = models.PositiveIntegerField(default=0, db_default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="", db_default="")
    last_error_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "next_attempt_at", "id"], name="notifydelivery_due_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["event", "subscription"],
                name="unique_notification_event_subscription",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=(
                        "pending",
                        "processing",
                        "delivered",
                        "expired",
                        "unavailable",
                        "failed",
                    )
                ),
                name="notifydelivery_status_valid",
            ),
        ]


period_choices = (
    ('daily', 'Daily'),
    ('weekly', 'Weekly'),
    ('fortnightly', 'Fortnightly'),
    ('monthly', 'Monthly'),
    ('quarterly', 'Quarterly'),
    ('yearly', 'Yearly'),
)

commitment_type_choices = (
    ('time', 'Time-based'),
    ('sessions', 'Session-based'),
)

aggregation_type_choices = (
    ('context', 'Context'),
    ('tag', 'Tag'),
    ('project', 'Project'),
    ('subproject', 'Subproject'),
)


class Commitment(models.Model):
    """
    Optional commitment tracking across project aggregations.
    Tracks whether users are meeting their time/session goals with time-banking.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='commitments')
    aggregation_type = models.CharField(max_length=20, choices=aggregation_type_choices, default='project')
    project = models.OneToOneField(Projects, on_delete=models.CASCADE, related_name='commitment', null=True, blank=True)
    subproject = models.OneToOneField(SubProjects, on_delete=models.CASCADE, related_name='commitment', null=True, blank=True)
    context = models.OneToOneField(Context, on_delete=models.CASCADE, related_name='commitment', null=True, blank=True)
    tag = models.OneToOneField(Tag, on_delete=models.CASCADE, related_name='commitment', null=True, blank=True)
    include_projects = models.ManyToManyField(
        Projects,
        blank=True,
        related_name='commitments_including',
    )
    exclude_projects = models.ManyToManyField(
        Projects,
        blank=True,
        related_name='commitments_excluding',
    )
    include_subprojects = models.ManyToManyField(
        SubProjects,
        blank=True,
        related_name='commitments_including',
    )
    exclude_subprojects = models.ManyToManyField(
        SubProjects,
        blank=True,
        related_name='commitments_excluding',
    )
    include_contexts = models.ManyToManyField(
        Context,
        blank=True,
        related_name='commitments_including',
    )
    exclude_contexts = models.ManyToManyField(
        Context,
        blank=True,
        related_name='commitments_excluding',
    )
    include_tags = models.ManyToManyField(
        Tag,
        blank=True,
        related_name='commitments_including',
    )
    exclude_tags = models.ManyToManyField(
        Tag,
        blank=True,
        related_name='commitments_excluding',
    )

    commitment_type = models.CharField(max_length=10, choices=commitment_type_choices, default='time')
    period = models.CharField(max_length=15, choices=period_choices, default='weekly')
    start_date = models.DateField(
        default=timezone.localdate,
        help_text='Date when commitment period calculations begin',
    )
    target = models.PositiveIntegerField(help_text='Minutes (time) or count (sessions)')

    # Banking
    balance = models.IntegerField(default=0)
    max_balance = models.PositiveIntegerField(default=600, help_text='Maximum balance cap (10 hours default)')
    min_balance = models.IntegerField(default=-600, help_text='Minimum balance cap (10 hours deficit default)')
    banking_enabled = models.BooleanField(default=True)
    notifications_enabled = models.BooleanField(default=False, db_default=False)

    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_reconciled = models.DateTimeField(null=True, blank=True)
    needs_recompute = models.BooleanField(default=False, db_default=False)
    ledger_start_at = models.DateTimeField(null=True, blank=True)
    generation = models.IntegerField(default=1, db_default=1)
    version = models.IntegerField(default=1, db_default=1)

    class Meta:
        verbose_name = 'Commitment'
        verbose_name_plural = 'Commitments'

    def __str__(self):
        type_label = 'min' if self.commitment_type == 'time' else 'sessions'
        return f"{self.target_name}: {self.target} {type_label}/{self.period}"

    @property
    def target_object(self):
        return {
            'project': self.project,
            'subproject': self.subproject,
            'context': self.context,
            'tag': self.tag,
        }.get(self.aggregation_type)

    @property
    def target_name(self):
        target = self.target_object
        return target.name if target else 'Unknown target'

    def clean(self):
        super().clean()
        targets = {
            'project': self.project,
            'subproject': self.subproject,
            'context': self.context,
            'tag': self.tag,
        }

        active_targets = [key for key, value in targets.items() if value is not None]
        if len(active_targets) != 1:
            raise ValidationError('Exactly one commitment target must be set.')

        if self.aggregation_type not in targets:
            raise ValidationError('Invalid aggregation type selected.')

        if targets.get(self.aggregation_type) is None:
            raise ValidationError('Aggregation type must match the selected target.')

        target = targets[self.aggregation_type]
        if getattr(target, 'user_id', None) != self.user_id:
            raise ValidationError('Commitment target must belong to the same user.')


class CommitmentRevision(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_ACTIVE = 'active'
    STATUS_CHOICES = (
        (STATUS_PENDING, 'Pending'),
        (STATUS_ACTIVE, 'Active'),
    )

    commitment = models.ForeignKey(
        Commitment,
        on_delete=models.CASCADE,
        related_name='revisions',
    )
    generation = models.IntegerField(default=1, db_default=1)
    effective_from_instant = models.DateTimeField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    aggregation_type = models.CharField(max_length=20, choices=aggregation_type_choices)
    target_id = models.BigIntegerField(null=True, blank=True)
    target_name = models.CharField(max_length=255, default='', db_default='')
    filters_snapshot = models.JSONField(default=dict)
    commitment_type = models.CharField(max_length=10, choices=commitment_type_choices)
    cadence = models.CharField(max_length=15, choices=period_choices)
    target_value = models.PositiveIntegerField()
    banking_enabled = models.BooleanField(default=True, db_default=True)
    max_balance = models.IntegerField(default=600, db_default=600)
    min_balance = models.IntegerField(default=-600, db_default=-600)
    start_date = models.DateField()
    timezone = models.CharField(max_length=64, default='Europe/Prague', db_default='Europe/Prague')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['commitment'],
                condition=models.Q(status='pending'),
                name='one_pending_revision_per_commitment',
            ),
        ]


class CommitmentPeriod(models.Model):
    commitment = models.ForeignKey(
        Commitment,
        on_delete=models.CASCADE,
        related_name='period_rows',
    )
    generation = models.IntegerField(default=1, db_default=1)
    revision = models.ForeignKey(
        CommitmentRevision,
        # Preserve revisions while period rows reference them, but permit a
        # commitment-family cascade to remove both sides together.
        on_delete=models.RESTRICT,
        related_name='period_rows',
    )
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    accrued_numerator = models.BigIntegerField(default=0, db_default=0)
    session_count = models.IntegerField(default=0, db_default=0)
    carryover_in = models.IntegerField(default=0, db_default=0)
    balance_out = models.IntegerField(default=0, db_default=0)
    closed_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['commitment', 'generation', 'period_start'],
                name='unique_commitment_generation_period_start',
            ),
        ]


class CommitmentAdjustment(models.Model):
    KIND_OPENING = 'opening'
    KIND_RESTART_CARRY = 'restart_carry'
    KIND_MANUAL = 'manual'
    KIND_CHOICES = (
        (KIND_OPENING, 'Opening'),
        (KIND_RESTART_CARRY, 'Restart carry'),
        (KIND_MANUAL, 'Manual'),
    )

    commitment = models.ForeignKey(
        Commitment,
        on_delete=models.CASCADE,
        related_name='adjustments',
    )
    seq = models.IntegerField()
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    amount = models.IntegerField()
    effective_at = models.DateTimeField()
    reason = models.TextField(default='', db_default='')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['commitment', 'seq'],
                name='unique_commitment_adjustment_seq',
            ),
        ]
