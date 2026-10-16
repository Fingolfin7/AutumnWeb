from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.models import (
    NotificationDelivery,
    NotificationEvent,
    PushSubscription,
)
from core.services.notification_retention import cleanup_notification_history


class NotificationHistoryRetentionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "retention-user", email="retention-user@example.com"
        )
        self.now = timezone.now().replace(microsecond=0)

    def event(self, *, completed_at, status="delivered"):
        return NotificationEvent.objects.create(
            dedupe_key=f"retention:{NotificationEvent.objects.count()}",
            event_type="reminder",
            user=self.user,
            payload={},
            scheduled_at=completed_at,
            status=status,
            completed_at=completed_at,
        )

    def test_cleanup_deletes_old_terminal_events_but_keeps_boundary_and_recent(self):
        old = self.event(completed_at=self.now - timedelta(days=90, seconds=1))
        boundary = self.event(completed_at=self.now - timedelta(days=90))
        recent = self.event(completed_at=self.now - timedelta(days=89))

        deleted = cleanup_notification_history(now=self.now, retention_days=90)

        self.assertEqual(deleted, 1)
        self.assertFalse(NotificationEvent.objects.filter(pk=old.pk).exists())
        self.assertTrue(NotificationEvent.objects.filter(pk=boundary.pk).exists())
        self.assertTrue(NotificationEvent.objects.filter(pk=recent.pk).exists())

    def test_live_delivery_protects_old_event_and_dry_run_is_non_mutating(self):
        event = self.event(completed_at=self.now - timedelta(days=91))
        subscription = PushSubscription.objects.create(
            user=self.user,
            endpoint="https://push.example.test/retention",
            p256dh="key",
            auth="auth",
        )
        delivery = NotificationDelivery.objects.create(
            event=event, subscription=subscription, status="pending"
        )

        self.assertEqual(
            cleanup_notification_history(
                now=self.now, retention_days=90, dry_run=True
            ),
            0,
        )
        self.assertTrue(NotificationEvent.objects.filter(pk=event.pk).exists())

        delivery.status = "delivered"
        delivery.save(update_fields=["status"])
        self.assertEqual(
            cleanup_notification_history(now=self.now, retention_days=90), 1
        )
        self.assertFalse(NotificationEvent.objects.filter(pk=event.pk).exists())

    def test_pending_and_processing_events_are_never_candidates(self):
        pending = self.event(
            completed_at=self.now - timedelta(days=91), status="pending"
        )
        processing = self.event(
            completed_at=self.now - timedelta(days=91), status="processing"
        )

        self.assertEqual(
            cleanup_notification_history(now=self.now, retention_days=90), 0
        )
        self.assertTrue(NotificationEvent.objects.filter(pk=pending.pk).exists())
        self.assertTrue(NotificationEvent.objects.filter(pk=processing.pk).exists())


    def test_cleanup_batch_is_hard_bounded(self):
        events = [
            self.event(completed_at=self.now - timedelta(days=91))
            for _ in range(3)
        ]

        self.assertEqual(
            cleanup_notification_history(
                now=self.now, retention_days=90, batch_size=2
            ),
            2,
        )
        self.assertEqual(
            NotificationEvent.objects.filter(pk__in=[event.pk for event in events]).count(),
            1,
        )
