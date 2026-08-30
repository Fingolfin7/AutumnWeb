"""Focused contracts for proactive notification delivery plumbing.

These tests exercise the provider-boundary payload contract and prove the
dispatcher can consume the proactive claim module without changing its
existing return shape.
"""

import json
import sys
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from core.services.push import PushValidationError, _serialize_payload
from core.services.reminder_dispatcher import run_dispatch_pass


class NotificationPayloadTests(SimpleTestCase):
    def test_two_actions_are_bounded_and_keep_safe_relative_routes(self):
        payload = json.loads(
            _serialize_payload(
                {
                    "kind": "scheduled_reminder",
                    "identity": "schedule-4:2026-08-30T16:30:00+00:00",
                    "title": "Planned focus",
                    "body": "Start the session.",
                    "url": "/notifications/",
                    "actions": [
                        {
                            "action": "start",
                            "label": "Start timer",
                            "url": "/start_timer/?project_id=4",
                        },
                        {
                            "action": "snooze",
                            "title": "Snooze",
                            "url": "/notifications/schedules/4/snooze/",
                        },
                    ],
                }
            )
        )

        self.assertEqual(len(payload["actions"]), 2)
        self.assertEqual(payload["actions"][0]["title"], "Start timer")
        self.assertEqual(payload["actions"][0]["label"], "Start timer")
        self.assertEqual(payload["actions"][1]["title"], "Snooze")
        self.assertEqual(payload["tag"], "autumn-scheduled_reminder-schedule-4:2026-08-30T16:30:00+00:00")

    def test_more_than_two_actions_and_unsafe_paths_are_rejected(self):
        base = {"title": "A", "body": "B", "url": "/notifications/"}
        with self.assertRaises(PushValidationError):
            _serialize_payload({**base, "actions": [{"title": "A", "url": "/timers/"}] * 3})
        with self.assertRaises(PushValidationError):
            _serialize_payload({**base, "url": "https://attacker.invalid/"})
        with self.assertRaises(PushValidationError):
            _serialize_payload(
                {
                    **base,
                    "actions": [{"title": "Open", "url": "/admin/"}],
                }
            )
        with self.assertRaises(PushValidationError):
            _serialize_payload(
                {
                    **base,
                    "actions": [{"title": "Open", "url": "/notifications/../admin/"}],
                }
            )
        with self.assertRaises(PushValidationError):
            _serialize_payload(
                {
                    **base,
                    "actions": [
                        {"action": "open", "title": "One", "url": "/timers/"},
                        {"action": "open", "title": "Two", "url": "/timers/"},
                    ],
                }
            )

    def test_legacy_payload_gets_stable_identity_and_safe_defaults(self):
        first = json.loads(_serialize_payload({"title": "A", "body": "B"}))
        second = json.loads(_serialize_payload({"title": "A", "body": "B"}))

        self.assertEqual(first["url"], "/timers/")
        self.assertEqual(first["identity"], "general")
        self.assertEqual(first["tag"], "autumn-timer-general")
        self.assertEqual(first["tag"], second["tag"])

    def test_payload_is_small_even_with_large_user_text(self):
        serialized = _serialize_payload(
            {
                "kind": "weekly_review",
                "identity": "week-1",
                "title": "T" * 100_000,
                "body": "B" * 100_000,
                "url": "/review/weekly/",
                "private_config": "do not forward",
            }
        )
        self.assertLessEqual(len(serialized.encode("utf-8")), 4096)
        self.assertNotIn("private_config", serialized)


class DispatcherProactiveContractTests(SimpleTestCase):
    def test_future_claimers_are_combined_after_timer_claims(self):
        scheduled = mock.Mock(return_value=["scheduled"])
        commitment = mock.Mock(return_value=["commitment"])
        review = mock.Mock(return_value=["review"])
        with mock.patch(
            "core.services.proactive_notifications.claim_due_proactive_notifications",
            new=None,
        ), mock.patch(
            "core.services.proactive_notifications.claim_due_scheduled_reminders",
            scheduled,
        ), mock.patch(
            "core.services.proactive_notifications.claim_due_commitment_checks",
            commitment,
        ), mock.patch(
            "core.services.proactive_notifications.claim_due_weekly_reviews",
            review,
        ), mock.patch(
            "core.utils.stop_expired_timers", return_value=[]
        ), mock.patch(
            "core.services.reminders.claim_due_reminders", return_value=["timer"]
        ) as timer_claim, mock.patch(
            "core.services.push.flush_outbox", return_value=0
        ):
            result = run_dispatch_pass(limit=8)

        self.assertEqual(result, (0, ["timer", "scheduled", "commitment", "review"], 0))
        timer_claim.assert_called_once()
        for claimer, expected_limit in (
            (scheduled, 7),
            (commitment, 6),
            (review, 5),
        ):
            self.assertEqual(claimer.call_args.kwargs["limit"], expected_limit)
            self.assertEqual(claimer.call_args.kwargs["now"], timer_claim.call_args.kwargs["now"])

    def test_missing_future_module_preserves_timer_only_contract(self):
        with mock.patch.dict(sys.modules, {"core.services.proactive_notifications": None}), mock.patch(
            "core.utils.stop_expired_timers", return_value=[]
        ), mock.patch(
            "core.services.reminders.claim_due_reminders", return_value=["timer"]
        ), mock.patch(
            "core.services.push.flush_outbox", return_value=0
        ):
            self.assertEqual(run_dispatch_pass(limit=1), (0, ["timer"], 0))


class ServiceWorkerContractTests(SimpleTestCase):
    service_worker = Path(__file__).parent / "static" / "core" / "pwa" / "service-worker.js"

    def test_worker_has_category_routes_and_action_only_navigation(self):
        source = self.service_worker.read_text(encoding="utf-8")
        for route in (
            '"/notifications"',
            '"/start_timer"',
            '"/commitments"',
            '"/update_commitment"',
            '"/review/weekly"',
        ):
            self.assertIn(route, source)
        self.assertIn('self.addEventListener("notificationclick"', source)
        self.assertIn("notificationActions", source)
        self.assertIn("safeActionUrl", source)

        click_body = source.split('self.addEventListener("notificationclick"', 1)[1]
        click_body = click_body.split('self.addEventListener("fetch"', 1)[0]
        self.assertNotIn("fetch(", click_body)
