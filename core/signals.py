from django.db.models.signals import pre_save, post_save, pre_delete, m2m_changed
from django.dispatch import receiver
from django.db import transaction
from core.models import Sessions, Projects, SubProjects
import logging

logger = logging.getLogger('signals')


@receiver(pre_save, sender=Sessions)
def set_session_is_active(sender, instance, **kwargs):
    """Set session active status based on end_time."""
    # Only handle saved instances or when is_active is True
    if not instance.pk and not instance.is_active:
        return

    instance.is_active = not bool(instance.end_time)


# @receiver(post_save, sender=Sessions)
# def update_project_info(sender, instance, **kwargs):
#     """Update project and subproject times after session changes."""
#     if not instance.end_time or instance.is_active or not instance.pk:
#         return
#
#     with transaction.atomic():
#         # Reload instance with all related data
#         instance.refresh_from_db()
#         instance = Sessions.objects.select_related('project').prefetch_related(
#             'subprojects'
#         ).get(pk=instance.pk)
#
#         update_value = instance.duration or 0.0
#
#         logger.info(f"Updating session {instance.id}")
#         logger.info(f"Project: {instance.project}")
#         if len(instance.subprojects.all()) > 0:
#             logger.info(f"Subprojects: {[subproject.name for subproject in instance.subprojects.all()]}")
#         logger.info(f"Update value: {update_value}")
#         logger.info(f"Previous total: {instance.project.total_time}")
#
#         # Update project
#         instance.project.total_time = max(0, instance.project.total_time + update_value)
#         instance.project.save()
#
#         # Update subprojects
#         for sub_project in instance.subprojects.all():
#             sub_project.total_time = max(0, sub_project.total_time + update_value)
#             sub_project.save()
#
#         logger.info(f"New project total: {instance.project.total_time}\n")
#
#         # Update last_updated timestamps
#         if instance.end_time > instance.project.last_updated:
#             instance.project.last_updated = instance.end_time
#             instance.project.save()
#
#         for sub_project in instance.subprojects.all():
#             if not sub_project.last_updated or instance.end_time > sub_project.last_updated:
#                 sub_project.last_updated = instance.end_time
#                 sub_project.save()


@receiver(m2m_changed, sender=Sessions.subprojects.through)
def update_session_totals(sender, instance, action, **kwargs):
    if not instance.end_time or instance.is_active:
        return

    if action in ['post_add', 'post_remove', 'post_clear']:
        with transaction.atomic():
            # Reload instance with all related data
            instance.refresh_from_db()
            instance = Sessions.objects.select_related('project').prefetch_related(
                'subprojects'
            ).get(pk=instance.pk)

            update_value = instance.duration or 0.0

            # Update subprojects
            for sub_project in instance.subprojects.all():
                sub_project.total_time = max(0, sub_project.total_time + update_value)
                sub_project.save()

            for sub_project in instance.subprojects.all():
                if not sub_project.last_updated or instance.end_time > sub_project.last_updated:
                    sub_project.last_updated = instance.end_time
                    sub_project.save()


@receiver(post_save, sender=Sessions)
def update_totals_on_save(sender, instance, **kwargs):
    if not instance.end_time or instance.is_active:
        return

    with transaction.atomic():
        # Reload instance with all related data
        instance.refresh_from_db()
        instance = Sessions.objects.select_related('project').get(pk=instance.pk)

        update_value = instance.duration or 0.0

        # Update project
        instance.project.total_time = max(0, instance.project.total_time + update_value)
        instance.project.save()

        # Update subprojects
        for sub_project in instance.subprojects.all():
            sub_project.total_time = max(0, sub_project.total_time + update_value)
            sub_project.save()

        # Update last_updated timestamps
        if instance.end_time > instance.project.last_updated:
            instance.project.last_updated = instance.end_time
            instance.project.save()

        for sub_project in instance.subprojects.all():
            if not sub_project.last_updated or instance.end_time > sub_project.last_updated:
                sub_project.last_updated = instance.end_time
                sub_project.save()


@receiver(pre_delete, sender=Sessions)
def update_time_on_delete(sender, instance, **kwargs):
    """Update project and subproject times before session deletion."""
    if instance.is_active or not instance.pk:
        return

    with transaction.atomic():
        # Reload instance to ensure we have latest data
        instance.refresh_from_db()
        instance = Sessions.objects.select_related('project').prefetch_related(
            'subprojects'
        ).get(pk=instance.pk)

        update_value = -instance.duration or 0.0

        logger.info(f"Deleting session {instance.id}")
        logger.info(f"Project: {instance.project}")
        if len(instance.subprojects.all()) > 0:
            logger.info(f"Subprojects: {[subproject.name for subproject in instance.subprojects.all()]}")
        logger.info(f"Update value: {update_value}")
        logger.info(f"Previous total: {instance.project.total_time}")

        # Update project
        instance.project.total_time = max(0, instance.project.total_time + update_value)
        instance.project.save()

        # Update subprojects
        for sub_project in instance.subprojects.all():
            sub_project.total_time = max(0, sub_project.total_time + update_value)
            sub_project.save()

        logger.info(f"New project total: {instance.project.total_time}\n")