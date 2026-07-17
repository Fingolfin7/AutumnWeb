from datetime import datetime, time, timezone as dt_tz
import uuid

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
    allocation_mode = models.CharField(
        max_length=16,
        choices=[('legacy_full', 'legacy_full'), ('partitioned', 'partitioned')],
        default='legacy_full',
        db_default='legacy_full',
    )
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)
    auto_stop_at = models.DateTimeField(null=True, blank=True)
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
        on_delete=models.PROTECT,
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
