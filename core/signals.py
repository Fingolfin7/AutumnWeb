"""Core signal registrations.

Session totals deliberately do not use model signals. A scalar save and the
following many-to-many update are separate events, so no signal sees a complete
before/after edit. Normal mutations use core.services instead.
"""

from django.db.models.signals import (
    m2m_changed,
    post_delete,
    post_save,
    pre_delete,
)
from django.dispatch import receiver

from core.models import (
    Commitment,
    NotificationDelivery,
    NotificationEvent,
    NotificationPreference,
    Projects,
    ScheduledReminder,
    Sessions,
    TimerReminder,
)


def _wake_reminder_dispatcher_after_commit(**kwargs):
    # Import lazily: signals are loaded from CoreConfig.ready(), which also
    # owns dispatcher startup and must remain safe during app initialization.
    from core.services.reminder_dispatcher import wake_dispatcher_on_commit

    wake_dispatcher_on_commit()


for _deadline_model in (
    Sessions,
    TimerReminder,
    ScheduledReminder,
    NotificationPreference,
    NotificationEvent,
    NotificationDelivery,
):
    post_save.connect(
        _wake_reminder_dispatcher_after_commit,
        sender=_deadline_model,
        dispatch_uid=(
            f"wake_reminder_dispatcher_save_{_deadline_model._meta.label_lower}"
        ),
    )
    post_delete.connect(
        _wake_reminder_dispatcher_after_commit,
        sender=_deadline_model,
        dispatch_uid=(
            f"wake_reminder_dispatcher_delete_{_deadline_model._meta.label_lower}"
        ),
    )


@receiver(m2m_changed, sender=Projects.tags.through)
def mark_commitments_dirty_for_project_tag_change(sender, instance, action, **kwargs):
    if action in {"post_add", "post_remove", "post_clear"}:
        Commitment.objects.filter(user_id=instance.user_id).update(
            needs_recompute=True
        )


def _cancel_pending_source_events(**source):
    """Make a disappearing notification source inert before its FK is nulled.

    The event foreign keys intentionally use ``SET_NULL`` so delivery history
    survives source deletion.  A pre-delete hook is therefore the lifecycle
    boundary that prevents a queued event from becoming a stale push.  Signals
    cover instance deletes, queryset deletes, and cascades from target objects.
    """

    NotificationEvent.objects.filter(status="pending", **source).update(
        status="cancelled",
        next_attempt_at=None,
        lease_until=None,
    )


@receiver(pre_delete, sender=ScheduledReminder)
def cancel_scheduled_reminder_events_before_delete(sender, instance, **kwargs):
    _cancel_pending_source_events(scheduled_reminder_id=instance.pk)


@receiver(pre_delete, sender=Commitment)
def cancel_commitment_events_before_delete(sender, instance, **kwargs):
    _cancel_pending_source_events(commitment_id=instance.pk)
