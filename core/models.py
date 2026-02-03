from datetime import datetime, time
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
            return round((timezone.make_aware(datetime.now()) - self.start_time).total_seconds() / 60.0, 4)
        else:
            return round((self.end_time - self.start_time).total_seconds() / 60.0, 4)


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


class Commitment(models.Model):
    """
    Optional commitment tracking for projects.
    Tracks whether users are meeting their time/session goals with time-banking.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='commitments')
    project = models.OneToOneField(Projects, on_delete=models.CASCADE, related_name='commitment')

    commitment_type = models.CharField(max_length=10, choices=commitment_type_choices, default='time')
    period = models.CharField(max_length=15, choices=period_choices, default='weekly')
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
        return f"{self.project.name}: {self.target} {type_label}/{self.period}"
