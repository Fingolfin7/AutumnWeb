from django.db.models.signals import pre_save, post_save, pre_delete
from django.dispatch import receiver
from core.models import Sessions
from django.db import transaction
import logging

# use the signals logger
logger = logging.getLogger('signals')


@receiver(pre_save, sender=Sessions)
def set_session_is_active(sender, instance, **kwargs):
    if instance.end_time:  # when there is a value for end_time
        instance.is_active = False
    else:  # set to active if end_time is None
        instance.is_active = True


@receiver(pre_save, sender=Sessions)
def update_project_time(sender, instance, **kwargs):
    if not instance.end_time:
        return

    with transaction.atomic():
        if instance.pk:
            old_instance = Sessions.objects.get(pk=instance.pk)
            if old_instance.end_time:
                update_value = instance.duration - old_instance.duration
            else:
                update_value = instance.duration
        else:
            update_value = instance.duration

        if abs(update_value) < 1e-9:  # floating point comparison allowance
            return

        logger.info(f"Saving/Updating session {instance.id}.")
        logger.info(
            f"Project: {instance.project}, "
            f"Subprojects: {[subproject.name for subproject in instance.subprojects.all()]}")
        logger.info(f"Project total time before update: {instance.project.total_time}")
        logger.info(f"Change/update value: {update_value}")

        instance.project.total_time += update_value
        instance.project.save()

        for sub_project in instance.subprojects.all():
            sub_project.total_time += update_value
            sub_project.save()

        logger.info(f"Project total time after update: {instance.project.total_time}\n")


@receiver(post_save, sender=Sessions)
def update_last_updated(sender, instance, **kwargs):
    if not instance.end_time:
        return

    with transaction.atomic():
        if instance.end_time > instance.project.last_updated:
            instance.project.last_updated = instance.end_time
            instance.project.save()

        instance = Sessions.objects.prefetch_related('subprojects').get(pk=instance.pk)

        for sub_project in instance.subprojects.all():
            if not sub_project.last_updated:
                sub_project.last_updated = instance.end_time
            elif instance.end_time > sub_project.last_updated:
                sub_project.last_updated = instance.end_time
            sub_project.save()


@receiver(pre_delete, sender=Sessions)
def update_project_time_on_delete(sender, instance, **kwargs):
    if instance.is_active:
        return

    with transaction.atomic():
        update_value = -instance.duration  # subtract the duration of the session

        logger.info(f"Deleting session {instance.id}.")
        logger.info(
            f"Project: {instance.project}, "
            f"Subprojects: {[subproject.name for subproject in instance.subprojects.all()]}")
        logger.info(f"Project total time before deletion: {instance.project.total_time}")
        logger.info(f"Change/update value: {update_value}")

        instance.project.total_time += update_value
        instance.project.save()

        for sub_project in instance.subprojects.all():
            sub_project.total_time += update_value
            sub_project.save()

        logger.info(f"Project total time after deletion: {instance.project.total_time}\n")
