import base64
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import NotificationDelivery, NotificationEvent, PushSubscription
from core.services.push import (
    PushValidationError,
    _serialize_payload,
    dispatch_event,
    enqueue_push_test,
    save_subscription,
    validate_subscription,
    vapid_configuration,
)


P256DH = "B" * 87  # 65 bytes when decoded, with URL-safe padding omitted
AUTH = "Y" * 22  # 16 bytes when decoded
VAPID_PUBLIC = base64.urlsafe_b64encode(b"\x04" + b"v" * 64).rstrip(b"=").decode()
# py_vapid reads a 32-byte value as a raw key, so this loads the way a real
# deployment's private key does without keeping a PEM file in the repository.
VAPID_PRIVATE = base64.urlsafe_b64encode(b"k" * 32).rstrip(b"=").decode()
PEM_CONTENTS = "-----BEGIN PRIVATE KEY-----\nMIGHAgEA\n-----END PRIVATE KEY-----\n"


class ProviderError(Exception):
    def __init__(self, status_code):
        self.response = SimpleNamespace(status_code=status_code)
        super().__init__(f"provider returned {status_code}")


class PushTestMixin:
    def payload(self, endpoint="https://push.example.test/send/abc"):
        return {
            "endpoint": endpoint,
            "expirationTime": None,
            "keys": {"p256dh": P256DH, "auth": AUTH},
        }

    def event(self, user, **values):
        values.setdefault("event_type", "reminder")
        values.setdefault("payload", {"title": "Test", "body": "Body"})
        values.setdefault("scheduled_at", timezone.now())
        return NotificationEvent.objects.create(
            dedupe_key=f"test:{user.pk}:{NotificationEvent.objects.count()}",
            user=user,
            **values,
        )


@override_settings(
    PUSH_VAPID_PUBLIC_KEY=VAPID_PUBLIC,
    PUSH_VAPID_PRIVATE_KEY=VAPID_PRIVATE,
    PUSH_VAPID_SUBJECT="mailto:test@example.com",
    PUSH_MAX_ATTEMPTS=2,
    PUSH_RETRY_BASE_SECONDS=5,
    PUSH_ALLOWED_ENDPOINT_SUFFIXES=("example.test",),
)
class PushDeliveryTests(PushTestMixin, TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "push-user", email="push-user@example.com", password="password"
        )
        self.other = User.objects.create_user(
            "other-push-user", email="other-push-user@example.com", password="password"
        )

    def test_subscription_validation_rejects_invalid_and_private_endpoints(self):
        with self.assertRaises(PushValidationError):
            validate_subscription(self.payload("http://push.example.test/send"))
        with self.assertRaises(PushValidationError):
            validate_subscription(self.payload("https://127.0.0.1/send"))
        with self.assertRaises(PushValidationError):
            validate_subscription(self.payload("https://attacker.invalid/send"))
        with self.assertRaises(PushValidationError):
            validate_subscription(
                {"endpoint": "https://push.example.test/send", "keys": {}}
            )

    def test_endpoint_is_globally_unique_and_transfer_cancels_old_delivery(self):
        subscription = save_subscription(user=self.user, payload=self.payload())
        event = self.event(self.user)
        delivery = NotificationDelivery.objects.create(
            event=event, subscription=subscription, status="pending"
        )

        transferred = save_subscription(user=self.other, payload=self.payload())

        self.assertEqual(transferred.pk, subscription.pk)
        self.assertEqual(PushSubscription.objects.get(pk=subscription.pk).user_id, self.other.pk)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, "unavailable")
        self.assertEqual(PushSubscription.objects.filter(endpoint=subscription.endpoint).count(), 1)

    def test_push_test_is_a_queued_event_and_never_calls_provider(self):
        client = Client()
        client.force_login(self.user)
        with mock.patch("core.services.push.webpush") as provider:
            response = client.post(
                reverse("push_test"), data="{}", content_type="application/json"
            )

        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.json()["queued"])
        provider.assert_not_called()
        event = NotificationEvent.objects.get(pk=response.json()["event_id"])
        self.assertEqual(event.payload["kind"], "test")

    def test_push_test_does_not_accept_an_arbitrary_endpoint(self):
        client = Client()
        client.force_login(self.user)
        response = client.post(
            reverse("push_test"),
            data={"endpoint": "https://attacker.example/send"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(NotificationEvent.objects.exists())

    def test_push_post_endpoints_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(
            reverse("push_test"), data="{}", content_type="application/json"
        )
        self.assertEqual(response.status_code, 403)

    def test_subscribe_status_and_unsubscribe_are_authenticated(self):
        client = Client()
        self.assertIn(
            client.get(reverse("push_status")).status_code,
            {302, 403},
        )
        client.force_login(self.user)
        response = client.post(
            reverse("push_subscribe"),
            data=self.payload(),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        status = client.get(reverse("push_status"))
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["subscriptions"], 1)
        self.assertNotIn(VAPID_PRIVATE, status.content.decode())

        response = client.post(
            reverse("push_unsubscribe"),
            data={"endpoint": self.payload()["endpoint"]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["removed"])
        self.assertFalse(PushSubscription.objects.get().active)

    @override_settings(
        PUSH_VAPID_PUBLIC_KEY=f"Application Server Key = {VAPID_PUBLIC}\n\n",
    )
    def test_status_normalises_py_vapid_cli_output(self):
        client = Client()
        client.force_login(self.user)

        configuration = vapid_configuration()
        response = client.get(reverse("push_status"))

        self.assertTrue(configuration["configured"])
        self.assertEqual(configuration["public_key"], VAPID_PUBLIC)
        self.assertTrue(response.json()["available"])
        self.assertEqual(response.json()["public_key"], VAPID_PUBLIC)

    def test_status_canonicalises_standard_base64_and_padded_public_keys(self):
        # The VAPID_PUBLIC bytes never encode to "+" or "/", so this key body
        # exercises both the alphabet translation and the padding strip.
        raw = b"\x04" + b"\xfb\xff" * 32
        client = Client()
        client.force_login(self.user)

        for value in (
            base64.b64encode(raw).decode(),
            base64.urlsafe_b64encode(raw).decode(),
        ):
            with self.subTest(value=value), override_settings(
                PUSH_VAPID_PUBLIC_KEY=value
            ):
                key = client.get(reverse("push_status")).json()["public_key"]
                self.assertRegex(key, r"^[A-Za-z0-9_-]+$")
                self.assertEqual(
                    base64.urlsafe_b64decode(key + "=" * (-len(key) % 4)), raw
                )

    def test_status_rejects_subjects_py_vapid_would_reject_at_send_time(self):
        client = Client()
        client.force_login(self.user)

        for subject in ("https://example.com/contact", "mailto:admin"):
            with self.subTest(subject=subject), override_settings(
                PUSH_VAPID_SUBJECT=subject
            ):
                body = client.get(reverse("push_status")).json()
                self.assertFalse(body["available"])
                self.assertIsNone(body["public_key"])
                self.assertIn("PUSH_VAPID_SUBJECT", body["configuration_error"])

    @override_settings(PUSH_VAPID_PRIVATE_KEY=PEM_CONTENTS)
    def test_status_rejects_raw_pem_contents_as_the_private_key(self):
        client = Client()
        client.force_login(self.user)

        configuration = vapid_configuration()
        response = client.get(reverse("push_status"))

        self.assertFalse(configuration["configured"])
        self.assertIn("PUSH_VAPID_PRIVATE_KEY", str(configuration["error"]))
        self.assertFalse(response.json()["available"])
        self.assertIsNone(response.json()["public_key"])

    @override_settings(PUSH_VAPID_PUBLIC_KEY="not a base64url key")
    def test_status_rejects_malformed_public_key_before_browser_decode(self):
        client = Client()
        client.force_login(self.user)

        response = client.get(reverse("push_status"))

        self.assertFalse(response.json()["available"])
        self.assertIsNone(response.json()["public_key"])
        self.assertIn("PUSH_VAPID_PUBLIC_KEY", response.json()["configuration_error"])

    def test_dispatch_fans_out_and_success_aggregates_with_expired_device(self):
        first = save_subscription(
            user=self.user, payload=self.payload("https://push.example.test/one")
        )
        second = save_subscription(
            user=self.user, payload=self.payload("https://push.example.test/two")
        )
        event = self.event(self.user)

        expired = ProviderError(410)
        with mock.patch(
            "core.services.push.send_push", side_effect=[None, expired]
        ) as sender:
            status = dispatch_event(event.pk, now=timezone.now())

        self.assertEqual(
            status,
            "delivered",
            list(NotificationDelivery.objects.filter(event=event).values_list("status", flat=True)),
        )
        event.refresh_from_db()
        self.assertEqual(event.status, "delivered")
        self.assertEqual(
            set(NotificationDelivery.objects.filter(event=event).values_list("status", flat=True)),
            {"delivered", "expired"},
        )
        self.assertEqual(PushSubscription.objects.filter(user=self.user, active=False).count(), 1)
        self.assertEqual(sender.call_count, 2)

    def test_permanent_four_hundred_failure_is_terminal_and_not_retried(self):
        subscription = save_subscription(user=self.user, payload=self.payload())
        event = self.event(self.user)
        error = ProviderError(400)
        with mock.patch("core.services.push.send_push", side_effect=error) as sender:
            status = dispatch_event(event.pk, now=timezone.now())
            again = dispatch_event(event.pk, now=timezone.now() + timedelta(minutes=1))

        self.assertEqual(status, "failed")
        self.assertEqual(again, "failed")
        self.assertEqual(sender.call_count, 1)
        self.assertEqual(
            NotificationDelivery.objects.get(event=event, subscription=subscription).status,
            "failed",
        )

    def test_transient_failure_is_bounded_then_dead_letters(self):
        subscription = save_subscription(user=self.user, payload=self.payload())
        event = self.event(self.user)
        error = Exception("provider unavailable")
        now = timezone.now()
        with mock.patch("core.services.push.send_push", side_effect=error):
            self.assertEqual(dispatch_event(event.pk, now=now), "pending")
        delivery = NotificationDelivery.objects.get(event=event, subscription=subscription)
        self.assertEqual(delivery.status, "pending")
        self.assertEqual(delivery.attempts, 1)
        delivery.next_attempt_at = now - timedelta(seconds=1)
        delivery.save(update_fields=["next_attempt_at"])
        with mock.patch("core.services.push.send_push", side_effect=error):
            self.assertEqual(dispatch_event(event.pk, now=now), "failed")
        delivery.refresh_from_db()
        event.refresh_from_db()
        self.assertEqual(delivery.status, "failed")
        self.assertEqual(delivery.attempts, 2)
        self.assertEqual(event.status, "failed")

    def test_stale_processing_lease_can_be_reclaimed(self):
        subscription = save_subscription(user=self.user, payload=self.payload())
        event = self.event(self.user)
        delivery = NotificationDelivery.objects.create(
            event=event,
            subscription=subscription,
            status="processing",
            lease_until=timezone.now() - timedelta(minutes=5),
            attempts=1,
        )
        with mock.patch("core.services.push.send_push") as sender:
            status = dispatch_event(event.pk, now=timezone.now())
        self.assertEqual(status, "delivered")
        self.assertEqual(sender.call_count, 1)
        delivery.refresh_from_db()
        self.assertEqual(delivery.attempts, 2)

    def test_missing_vapid_and_no_recipient_are_terminal(self):
        event = self.event(self.user)
        with override_settings(
            PUSH_VAPID_PUBLIC_KEY="", PUSH_VAPID_PRIVATE_KEY="", PUSH_VAPID_SUBJECT=""
        ):
            self.assertEqual(dispatch_event(event.pk), "unavailable")
        event.refresh_from_db()
        self.assertEqual(event.status, "unavailable")

        event = self.event(self.user)
        with mock.patch("core.services.push.send_push") as sender:
            self.assertEqual(dispatch_event(event.pk), "unavailable")
        sender.assert_not_called()

    def test_enqueue_push_test_uses_fixed_payload(self):
        event = enqueue_push_test(user=self.user)
        self.assertEqual(event.event_type, "reminder")
        self.assertIsNone(event.session_id)
        self.assertEqual(event.payload["url"], "/timers/")

    def test_provider_payload_is_bounded(self):
        serialized = _serialize_payload({"title": "T", "body": "x" * 100_000})
        self.assertLessEqual(len(serialized.encode("utf-8")), 4096)


class DispatcherCommandTests(TestCase):
    def test_once_runs_the_global_pass_in_the_expected_order(self):
        output = StringIO()
        with mock.patch(
            "core.management.commands.dispatch_timer_reminders.cache.add", return_value=True
        ), mock.patch(
            "core.management.commands.dispatch_timer_reminders.cache.get", return_value=None
        ), mock.patch(
            "core.management.commands.dispatch_timer_reminders.Command._pass",
            return_value=(2, [object(), object()], 3),
        ) as one_pass:
            call_command("dispatch_timer_reminders", "--once", stdout=output)
        one_pass.assert_called_once()
        self.assertIn("stopped=2 claimed=2 flushed=3", output.getvalue())

    def test_second_dispatcher_exits_when_the_singleton_lock_is_held(self):
        output = StringIO()
        with mock.patch(
            "core.management.commands.dispatch_timer_reminders.cache.add", return_value=False
        ), mock.patch(
            "core.management.commands.dispatch_timer_reminders.Command._pass"
        ) as one_pass:
            call_command("dispatch_timer_reminders", "--once", stdout=output)
        one_pass.assert_not_called()
        self.assertIn("already running", output.getvalue())
