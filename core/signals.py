from django.db.models.signals import pre_save, post_save, pre_delete
from django.dispatch import receiver
from core.models import Sessions
from django.db import transaction
import logging

# use the signals logger
logger = logging.getLogger('signals')


@receiver(pre_save, sender=Sessions)
def set_session_is_active(sender, instance, **kwargs):
    if instance.is_active or not instance.pk:  # Also check if instance is saved here
        return

    if instance.end_time:  # when there is a value for end_time
        instance.is_active = False
    else:  # set to active if end_time is None
        instance.is_active = True


@receiver(pre_save, sender=Sessions)
def set_old_duration(sender, instance, **kwargs):
    if not instance.end_time or instance.is_active:
        return

    if instance.pk:
        instance.pre_save_duration = Sessions.objects.get(pk=instance.pk).duration
    else:
        instance.pre_save_duration = 0.0  # handle a new instance

    logger.info(f"Setting old duration for session {instance.id} to {instance.pre_save_duration}.\n")



@receiver(post_save, sender=Sessions)
def update_project_info(sender, instance, created, **kwargs):
    if not instance.end_time or instance.is_active or not instance.pk:
        return

    with transaction.atomic():
        update_value = instance.duration - instance.pre_save_duration

        instance = Sessions.objects.prefetch_related('subprojects').get(pk=instance.pk)

        # update the project and subprojects total times
        if abs(update_value) >= 1e-9:  # check if the update value is not too small
            logger.info(f"Saving/Updating session {instance.id}.")
            logger.info(f"Project: {instance.project}")
            if len(instance.subprojects.all()) > 0:
                logger.info(f"Subprojects: {[subproject.name for subproject in instance.subprojects.all()]}")
            logger.info(f"Project total time before update: {instance.project.total_time}")
            logger.info(f"Change/update value: {update_value}")

            instance.project.total_time += update_value
            instance.project.save()

            if instance.subprojects.exists() > 0:
                for sub_project in instance.subprojects.all():
                    sub_project.total_time += update_value
                    sub_project.save()

            logger.info(f"Project total time after update: {instance.project.total_time}\n")

        # update the project and subprojects last_updated fields
        if instance.end_time > instance.project.last_updated:
            instance.project.last_updated = instance.end_time
            instance.project.save()

        for sub_project in instance.subprojects.all():
            if not sub_project.last_updated or instance.end_time > sub_project.last_updated:
                sub_project.last_updated = instance.end_time
                sub_project.save()


@receiver(pre_delete, sender=Sessions)
def update_time_on_delete(sender, instance, **kwargs):
    if instance.is_active:
        return

    if instance.is_active or not instance.pk:  # Also check if instance is saved here
        return

    with transaction.atomic():
        update_value = -instance.duration  # subtract the duration of the session

        logger.info(f"Deleting session {instance.id}.")
        logger.info(f"Project: {instance.project}")
        if len(instance.subprojects.all()) > 0:
            logger.info(f"Subprojects: {[subproject.name for subproject in instance.subprojects.all()]}")
        logger.info(f"Project total time before deletion: {instance.project.total_time}")
        logger.info(f"Change/update value: {update_value}")

        instance.project.total_time += update_value
        instance.project.save()

        if instance.subprojects.exists() > 0:
            for sub_project in instance.subprojects.all():
                sub_project.total_time += update_value
                sub_project.save()


        if instance.subprojects.all().count() == 0:
            if instance.project.total_time <= 0.001:
                logger.info(f"Final project time after delete: {instance.project.total_time}\n")
            elif instance.project.total_time < 0.001:
                logger.error(f"Error! Negative time value after update: {instance.project.total_time}\n")
            # else:
            #     logger.error(f"Error! Larger time value after update: {instance.project.total_time}\n")
        else:
            logger.info(f"Project total time after delete: {instance.project.total_time}\n")
