from django.db.models.signals import pre_save
from django.dispatch import receiver
from core.models import Sessions


@receiver(pre_save, sender=Sessions)
def set_session_is_active(sender, instance, **kwargs):
    if instance.end_time is not None:
        instance.is_active = False

