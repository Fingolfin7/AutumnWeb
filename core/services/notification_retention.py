from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from core.models import NotificationDelivery, NotificationEvent


TERMINAL_EVENT_STATUSES = ("delivered", "unavailable", "failed", "cancelled")
LIVE_DELIVERY_STATUSES = ("pending", "processing")
MAX_CLEANUP_BATCH_SIZE = 1000


def cleanup_notification_history(*, now=None, retention_days=None, batch_size=None, dry_run=False):
    """Delete a bounded batch of old terminal events without touching live work."""
    now = now or timezone.now()
    if retention_days is None:
        retention_days = int(getattr(settings, "NOTIFICATION_HISTORY_RETENTION_DAYS", 90))
    if batch_size is None:
        batch_size = int(
            getattr(settings, "NOTIFICATION_HISTORY_CLEANUP_BATCH_SIZE", 100)
        )
    retention_days = int(retention_days)
    batch_size = min(MAX_CLEANUP_BATCH_SIZE, max(1, int(batch_size)))
    if retention_days <= 0:
        return 0

    cutoff = now - timedelta(days=retention_days)
    live_deliveries = NotificationDelivery.objects.filter(
        event_id=OuterRef("pk"), status__in=LIVE_DELIVERY_STATUSES
    )
    candidates = NotificationEvent.objects.filter(
        status__in=TERMINAL_EVENT_STATUSES,
        completed_at__isnull=False,
        completed_at__lt=cutoff,
    ).annotate(has_live_delivery=Exists(live_deliveries)).filter(
        has_live_delivery=False
    ).order_by("completed_at", "pk")[:batch_size]
    candidate_ids = list(candidates.values_list("pk", flat=True))
    if dry_run:
        return len(candidate_ids)

    deleted = 0
    for event_id in candidate_ids:
        with transaction.atomic():
            event = NotificationEvent.objects.select_for_update().filter(
                pk=event_id,
                status__in=TERMINAL_EVENT_STATUSES,
                completed_at__isnull=False,
                completed_at__lt=cutoff,
            ).first()
            if event is None or event.deliveries.filter(
                status__in=LIVE_DELIVERY_STATUSES
            ).exists():
                continue
            event.delete()
            deleted += 1
    return deleted
