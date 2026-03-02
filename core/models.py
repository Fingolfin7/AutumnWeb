from datetime import datetime, time, timezone as dt_tz
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
    total_time = models.FloatField(default=0.0)
    status = models.CharField(max_length=25, choices=status_choices, default='active')
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

    def audit_total_time(self, log=True):
        # Using select_related to fetch related projects in one query
        if log:
            logger.info(f"Auditing total time for project: {self.name}")
            logger.info(f"Total Time before audit: {self.total_time}")

        self.total_time = sum(
            session.duration for session in self.sessions.filter(is_active=False) if session.duration is not None)
        self.save()

        if log:
            logger.info(f"Total Time after audit: {self.total_time}\n")

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
    total_time = models.FloatField(default=0.0)
    description = models.TextField(null=True, blank=True)
    parent_project = models.ForeignKey(Projects, on_delete=models.CASCADE, related_name='subprojects')

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

    def audit_total_time(self, log=True):
        if log:
            logger.info(f"Auditing total time for subproject: {self.name}")
            logger.info(f"Total Time before audit: {self.total_time}")

        self.total_time = sum(
            session.duration for session in self.sessions.filter(is_active=False) if session.duration is not None)
        self.save()

        if log:
            logger.info(f"Total Time after audit: {self.total_time}\n")

    # when a subproject is deleted, remove it from all its sessions
    def delete(self, *args, **kwargs):
        for session in self.sessions.all():
            session.subprojects.remove(self)
            session.save()
        super(SubProjects, self).delete(*args, **kwargs)


class Sessions(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    project = models.ForeignKey(Projects, on_delete=models.CASCADE, related_name='sessions')
    subprojects = models.ManyToManyField(SubProjects, related_name='sessions')
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)
    note = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    crosses_dst_transition = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = 'Sessions'
        ordering = ['-end_time']

        indexes = [
            models.Index(fields=['is_active', 'end_time']),  # Optimizes queries that filter active/completed sessions
            models.Index(fields=['user', 'project']),  # Optimizes lookups by user and project
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

    def save(self, *args, **kwargs):
        self.crosses_dst_transition = self._compute_crosses_dst_transition(
            self.start_time, self.end_time
        )
        super().save(*args, **kwargs)


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
