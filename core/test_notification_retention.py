from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.test import override_settings
from django.utils import timezone

from core.models import (
    NotificationDelivery,
    NotificationEvent,
    Projects,
    PushSubscription,
    Sessions,
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

    def test_pending_and_processing_deliveries_protect_terminal_event(self):
        event = self.event(completed_at=self.now - timedelta(days=91))
        subscription = PushSubscription.objects.create(
            user=self.user,
            endpoint="https://push.example.test/live-delivery",
            p256dh="key",
            auth="auth",
        )
        for index, status in enumerate(("pending", "processing")):
            NotificationDelivery.objects.create(
                event=event,
                subscription=subscription,
                status=status,
                # A second subscription is not needed for the protection check.
            )
            if index == 0:
                subscription = PushSubscription.objects.create(
                    user=self.user,
                    endpoint="https://push.example.test/live-delivery-2",
                    p256dh="key",
                    auth="auth",
                )

        self.assertEqual(
            cleanup_notification_history(now=self.now, retention_days=90), 0
        )
        self.assertTrue(NotificationEvent.objects.filter(pk=event.pk).exists())

    @override_settings(NOTIFICATION_HISTORY_RETENTION_DAYS=0)
    def test_zero_retention_is_disabled_without_a_database_query(self):
        with self.assertNumQueries(0):
            self.assertEqual(cleanup_notification_history(now=self.now), 0)

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

    def test_configured_batch_cannot_exceed_hard_cap(self):
        NotificationEvent.objects.bulk_create(
            [
                NotificationEvent(
                    dedupe_key=f"retention-cap:{index}",
                    event_type="reminder",
                    user=self.user,
                    payload={},
                    scheduled_at=self.now,
                    status="delivered",
                    completed_at=self.now - timedelta(days=91),
                )
                for index in range(1001)
            ]
        )

        self.assertEqual(
            cleanup_notification_history(
                now=self.now, retention_days=90, batch_size=5000
            ),
            1000,
        )
        self.assertEqual(NotificationEvent.objects.count(), 1)

    def test_dry_run_preserves_event_and_cleanup_preserves_session_source(self):
        project = Projects.objects.create(user=self.user, name="Retention project")
        session = Sessions.objects.create(
            user=self.user,
            project=project,
            start_time=self.now - timedelta(hours=1),
            end_time=self.now,
        )
        event = self.event(
            completed_at=self.now - timedelta(days=91),
        )
        event.session = session
        event.save(update_fields=["session"])

        self.assertEqual(
            cleanup_notification_history(now=self.now, dry_run=True), 1
        )
        self.assertTrue(NotificationEvent.objects.filter(pk=event.pk).exists())
        self.assertEqual(cleanup_notification_history(now=self.now), 1)
        self.assertTrue(Sessions.objects.filter(pk=session.pk).exists())
        self.assertTrue(Projects.objects.filter(pk=project.pk).exists())
