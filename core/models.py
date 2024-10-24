from datetime import datetime, time
from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
import logging

logger = logging.getLogger('models')

status_choices = (
    ('active', 'Active'),
    ('paused', 'Paused'),
    ('complete', 'Complete'),
)


User._meta.get_field('email')._unique = True  # make email field unique


# model to track the projects that a user is working on
class Projects(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    start_date = models.DateTimeField(default=timezone.now)
    last_updated = models.DateTimeField(default=timezone.now)
    total_time = models.FloatField(default=0.0)
    status = models.CharField(max_length=25, choices=status_choices, default='active')
    description = models.TextField(null=True, blank=True)

    class Meta:
        verbose_name_plural = 'Projects'
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def get_start(self):
        return datetime.combine(self.start_date, time())

    @property
    def get_end(self):
        return datetime.combine(self.last_updated, time())

    def audit_total_time(self):
        # Using select_related to fetch related projects in one query
        logging.info("Auditing total time for project: %s", self.name)
        logging.info("Total Time before audit: %s", self.total_time)
        self.total_time = sum(session.duration for session in self.sessions.all() if
                              session.duration is not None)
        self.save()
        logging.info("Total Time after audit: %s", self.total_time)


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

    def __str__(self):
        return self.name

    @property
    def get_start(self):
        return datetime.combine(self.start_date, time())

    @property
    def get_end(self):
        return datetime.combine(self.last_updated, time())

    def audit_total_time(self):
        logging.info("Auditing total time for subproject: %s", self.name)
        logging.info("Total Time before audit: %s", self.total_time)
        self.total_time = sum(session.duration for session in self.sessions.all() if session.duration is not None)
        self.save()
        logging.info("Total Time after audit: %s", self.total_time)

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
    pre_save_duration = models.FloatField(default=0.0)

    class Meta:
        verbose_name_plural = 'Sessions'
        ordering = ['-end_time']

    def __str__(self):
        sub_list = [sub.name for sub in self.subprojects.all()]
        return f"{self.project.name} {sub_list} - {self.start_time}"

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
        elif self.is_active:
            return (timezone.make_aware(datetime.now()) - self.start_time).total_seconds() / 60.0
        else:
            return (self.end_time - self.start_time).total_seconds() / 60.0
