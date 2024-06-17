from django.db.models.signals import pre_save, post_save, pre_delete
from django.dispatch import receiver
from core.models import Sessions


@receiver(pre_save, sender=Sessions)
def set_session_is_active(sender, instance, **kwargs):
    if instance.end_time:  # when there is a value for end_time
        instance.is_active = False
    else:  # set to active if end_time is None
        instance.is_active = True


@receiver(post_save, sender=Sessions)
def update_last_updated(sender, instance, **kwargs):
    if not instance.end_time:
        return

    if instance.end_time > instance.project.last_updated:
        instance.project.last_updated = instance.end_time
        instance.project.save()


    instance = Sessions.objects.prefetch_related('subprojects').get(pk=instance.pk)

    for sub_project in instance.subprojects.all():
        if instance.end_time > sub_project.last_updated:
            sub_project.last_updated = instance.end_time
            sub_project.save()

