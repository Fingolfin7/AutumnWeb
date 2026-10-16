"""Focused contracts for proactive notification delivery plumbing.

These tests exercise the provider-boundary payload contract and prove the
dispatcher can consume the proactive claim module without changing its
existing return shape.
"""

import json
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


class DispatcherProactiveContractTests(SimpleTestCase):
    def test_timer_backlog_leaves_no_budget_for_proactive_claims(self):
        with mock.patch(
            "core.services.proactive_notifications.claim_due_proactive_notifications"
        ) as proactive_claim, mock.patch(
            "core.utils.stop_expired_timers", return_value=[]
        ), mock.patch(
            "core.services.reminders.claim_due_reminders", return_value=["timer"]
        ), mock.patch(
            "core.services.push.flush_outbox", return_value=0
        ):
            self.assertEqual(run_dispatch_pass(limit=1), (0, ["timer"], 0))
        proactive_claim.assert_not_called()
