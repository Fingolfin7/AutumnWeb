"""Core signal registrations.

Session totals deliberately do not use model signals. A scalar save and the
following many-to-many update are separate events, so no signal sees a complete
before/after edit. Normal mutations use core.services instead.
"""

from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from core.models import Commitment, Projects


@receiver(m2m_changed, sender=Projects.tags.through)
def mark_commitments_dirty_for_project_tag_change(sender, instance, action, **kwargs):
    if action in {"post_add", "post_remove", "post_clear"}:
        Commitment.objects.filter(user_id=instance.user_id).update(
            needs_recompute=True
        )
