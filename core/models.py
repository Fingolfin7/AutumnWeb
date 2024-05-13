from django.db import models


status_choices = (
    ('active', 'Active'),
    ('paused', 'Paused'),
    ('completed', 'Completed'),
)


# model to track the projects that a user is working on
class Projects(models.Model):
    name = models.CharField(max_length=255, unique=True)
    start_date = models.DateField(auto_now=True)
    last_updated = models.DateField(auto_now=True)
    total_time = models.FloatField(default=0.0)
    status = models.CharField(max_length=25, choices=status_choices, default='active')

    class Meta:
        verbose_name_plural = 'Projects'

    def __str__(self):
        return self.name



class SubProjects(models.Model):
    name = models.CharField(max_length=255)
    start_date = models.DateField(auto_now=True)
    last_updated = models.DateField(auto_now=True)
    total_time = models.FloatField(default=0.0)
    parent_project = models.ForeignKey(Projects, on_delete=models.CASCADE)

    class Meta:
        verbose_name_plural = 'SubProjects'

    def __str__(self):
        return self.name


class Sessions(models.Model):
    project = models.ForeignKey(Projects, on_delete=models.CASCADE)
    subprojects = models.ManyToManyField(SubProjects)
    start_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(null=True, blank=True)
    note = models.TextField()
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = 'Sessions'

    def __str__(self):
        sub_list = [sub.name for sub in self.subprojects.all()]
        return f"{self.project.name} {sub_list} - {self.start_time}"

    @property
    def duration(self):
        if self.end_time is None:
            return None
        else:
            return (self.end_time - self.start_time).total_seconds() / 60.0


