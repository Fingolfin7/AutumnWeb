"""Core signal registrations.

Session totals deliberately do not use model signals. A scalar save and the
following many-to-many update are separate events, so no signal sees a complete
before/after edit. Normal mutations use core.session_ledger instead.
"""

from django.db.models.signals import pre_save
from django.dispatch import receiver

from core.models import Sessions


@receiver(pre_save, sender=Sessions)
def set_session_is_active(sender, instance, **kwargs):
    """Keep persisted timer state consistent with whether an end time exists."""
    if instance.pk or instance.is_active:
        instance.is_active = not bool(instance.end_time)
