from datetime import datetime, time
from django.db import models
from django.utils import timezone


status_choices = (
    ('active', 'Active'),
    ('paused', 'Paused'),
    ('completed', 'Completed'),
)


# model to track the projects that a user is working on
class Projects(models.Model):
    name = models.CharField(max_length=255, unique=True)
    start_date = models.DateTimeField(default=timezone.now)
    last_updated = models.DateTimeField(default=timezone.now)
    total_time = models.FloatField(default=0.0)
    status = models.CharField(max_length=25, choices=status_choices, default='active')


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
        self.total_time = sum(session.duration for session in self.sessions.all() if
                              session.duration is not None)
        self.save()


class SubProjects(models.Model):
    name = models.CharField(max_length=255)
    start_date = models.DateTimeField(default=timezone.now)
    last_updated = models.DateTimeField(null=True, blank=True)
    total_time = models.FloatField(default=0.0)
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
        self.total_time = sum(session.duration for session in self.sessions.all() if session.duration is not None)
        self.save()

    # when a subproject is deleted, remove it from all its sessions
    def delete(self, *args, **kwargs):
        for session in self.sessions.all():
            session.subprojects.remove(self)
            session.save()
        super(SubProjects, self).delete(*args, **kwargs)



class Sessions(models.Model):
    project = models.ForeignKey(Projects, on_delete=models.CASCADE, related_name='sessions')
    subprojects = models.ManyToManyField(SubProjects, related_name='sessions')
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)
    note = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = 'Sessions'
        ordering = ['-start_time']

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

    def save(self, *args, **kwargs):
        if self.is_active or self.end_time is None:
            super(Sessions, self).save(*args, **kwargs)
            return

        if self.pk:
            # Existing instance, get the previous duration
            previous_instance = Sessions.objects.get(pk=self.pk)
            previous_duration = previous_instance.duration
        else:
            previous_duration = 0


        super(Sessions, self).save(*args, **kwargs)

        # Calculate the difference in duration
        update_value = self.duration - previous_duration

        # if update_value < 0:
        #     print(f"Something weird happened: {update_value}, "
        #           f"start: {self.start_time}, end: {self.end_time}, "
        #           f"is_active: {self.is_active}")

        # Update parent project total time
        self.project.total_time += update_value
        self.project.save()

        # Update subprojects total time
        for sub_project in self.subprojects.all():
            sub_project.total_time += update_value
            sub_project.save()

    def delete(self, *args, **kwargs):
        if self.is_active:
            super(Sessions, self).delete(*args, **kwargs)
            return

        # Subtract the session duration from parent project and subprojects
        update_value = -self.duration

        self.project.total_time += update_value
        self.project.save()

        for sub_project in self.subprojects.all():
            sub_project.total_time += update_value
            sub_project.save()

        super(Sessions, self).delete(*args, **kwargs)



