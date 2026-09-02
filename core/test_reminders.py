from datetime import datetime, timedelta, timezone as dt_timezone
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from core.models import NotificationEvent, Projects, Sessions, TimerReminder
from core.services.reminders import (
    claim_due_reminders,
    create_timer_reminder,
    enqueue_auto_stop_event,
)
from core.services.sessions import SessionMutationService
from core.utils import stop_expired_timers


class TimerReminderServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("reminder-user", password="password")
        self.user.profile.timezone = "Europe/Prague"
        self.user.profile.save(update_fields=["timezone"])
        self.project = Projects.objects.create(user=self.user, name="Reminder project")
        self.start = datetime(2026, 1, 15, 10, 0, tzinfo=dt_timezone.utc)

    def session(self, **kwargs):
        return SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            subprojects=[],
            start_time=kwargs.pop("start_time", self.start),
            **kwargs,
        )

    def test_duration_reminders_use_whole_second_instants(self):
        session = self.session()
        reminder = create_timer_reminder(
            user=self.user,
            session=session,
            mode="after",
            amount=2,
            unit="minutes",
        )

        self.assertEqual(reminder.next_fire_at, self.start + timedelta(minutes=2))
        self.assertEqual(reminder.interval_seconds, None)

    def test_profile_timezone_rejects_dst_gap_and_fold(self):
        self.user.profile.timezone = "America/New_York"
        self.user.profile.save(update_fields=["timezone"])
        session = self.session()

        with self.assertRaises(ValidationError):
            create_timer_reminder(
                user=self.user,
                session=session,
                mode="at",
                at_local=datetime(2026, 3, 8, 2, 30),
            )
        with self.assertRaises(ValidationError):
            create_timer_reminder(
                user=self.user,
                session=session,
                mode="at",
                at_local=datetime(2026, 11, 1, 1, 30),
            )

    def test_interval_claim_skips_missed_occurrences(self):
        session = self.session()
        reminder = create_timer_reminder(
            user=self.user,
            session=session,
            mode="interval",
            amount=1,
            unit="minute",
        )
        now = self.start + timedelta(minutes=5, seconds=30)

        events = claim_due_reminders(now=now)

        self.assertEqual(len(events), 1)
        reminder.refresh_from_db()
        self.assertEqual(
            reminder.next_fire_at,
            self.start + timedelta(minutes=6),
        )
        self.assertEqual(NotificationEvent.objects.count(), 1)
        self.assertEqual(events[0].dedupe_key, f"reminder:{reminder.pk}:2026-01-15T10:01:00+00:00")

    def test_claim_is_idempotent_for_one_shot_and_outbox_key(self):
        session = self.session()
        reminder = create_timer_reminder(
            user=self.user,
            session=session,
            mode="after",
            amount=1,
            unit="minutes",
        )
        now = self.start + timedelta(minutes=2)

        first = claim_due_reminders(now=now)
        second = claim_due_reminders(now=now)
        duplicate = enqueue_auto_stop_event(session, self.start)
        duplicate_again = enqueue_auto_stop_event(session, self.start)

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(duplicate.pk, duplicate_again.pk)
        self.assertFalse(TimerReminder.objects.get(pk=reminder.pk).active)
        self.assertEqual(NotificationEvent.objects.filter(event_type="reminder").count(), 1)

    @mock.patch("core.services.reminders.timezone.now")
    def test_notification_copy_names_project_elapsed_time_and_expands_placeholders(
        self, now
    ):
        now.return_value = self.start
        session = self.session()
        create_timer_reminder(
            user=self.user,
            session=session,
            mode="after",
            amount=2,
            unit="minutes",
            message="Stretch after {elapsed} on {project}",
        )

        event = claim_due_reminders(now=self.start + timedelta(minutes=2))[0]

        self.assertEqual(event.payload["title"], "Reminder project timer reminder")
        self.assertEqual(
            event.payload["body"], "Stretch after 2m on Reminder project"
        )

    def test_stop_cancels_reminders_and_restart_does_not_revive_them(self):
        session = self.session()
        reminder = create_timer_reminder(
            user=self.user,
            session=session,
            mode="interval",
            amount=1,
            unit="minutes",
        )
        stopped = SessionMutationService.mutate_session(
            session.pk,
            user=self.user,
            end_time=self.start + timedelta(minutes=10),
        )
        reminder.refresh_from_db()
        self.assertFalse(reminder.active)
        self.assertIsNone(reminder.next_fire_at)
        self.assertEqual(reminder.cancelled_at, stopped.end_time)

        SessionMutationService.mutate_session(
            session.pk,
            user=self.user,
            start_time=self.start + timedelta(hours=1),
            end_time=None,
        )
        reminder.refresh_from_db()
        self.assertFalse(reminder.active)

    def test_auto_stop_is_compare_and_set_and_enqueues_once(self):
        deadline = self.start + timedelta(minutes=10)
        session = self.session(
            auto_stop_at=deadline,
            notify_on_auto_stop=True,
        )

        first = stop_expired_timers(self.user, now=deadline + timedelta(seconds=1))
        second = stop_expired_timers(self.user, now=deadline + timedelta(seconds=1))

        self.assertEqual([item.pk for item in first], [session.pk])
        self.assertEqual(second, [])
        session.refresh_from_db()
        self.assertEqual(session.end_time, deadline)
        self.assertEqual(
            NotificationEvent.objects.filter(
                event_type="auto_stop", session=session
            ).count(),
            1,
        )
        event = NotificationEvent.objects.get(event_type="auto_stop", session=session)
        self.assertEqual(event.payload["title"], "Reminder project timer stopped")
        self.assertIn("after 10m", event.payload["body"])

    def test_reminder_claim_does_not_call_push_network(self):
        session = self.session()
        create_timer_reminder(
            user=self.user,
            session=session,
            mode="after",
            amount=1,
            unit="minutes",
        )
        with mock.patch("core.services.push.send_push") as send_push:
            claim_due_reminders(now=self.start + timedelta(minutes=2))
        send_push.assert_not_called()


class ConcurrentTimerReminderTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user = User.objects.create_user("concurrent-reminder-user")
        self.project = Projects.objects.create(
            user=self.user, name="Concurrent reminder project"
        )
        self.start = datetime(2030, 1, 15, 10, 0, tzinfo=dt_timezone.utc)

    def _run_in_connection(self, operation):
        close_old_connections()
        try:
            return operation()
        finally:
            # CONN_MAX_AGE keeps healthy connections open, but executor worker
            # threads must not outlive their test database connections.
            connections.close_all()

    def test_two_claimers_create_one_reminder_event(self):
        session = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            subprojects=[],
            start_time=self.start,
        )
        create_timer_reminder(
            user=self.user,
            session=session,
            mode="after",
            amount=1,
            unit="minute",
        )
        due = self.start + timedelta(minutes=2)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda _: self._run_in_connection(
                        lambda: claim_due_reminders(now=due)
                    ),
                    range(2),
                )
            )

        self.assertEqual(sum(len(result) for result in results), 1)
        self.assertEqual(NotificationEvent.objects.filter(event_type="reminder").count(), 1)

    def test_two_auto_stop_sweeps_stop_and_enqueue_once(self):
        deadline = self.start + timedelta(minutes=10)
        session = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            subprojects=[],
            start_time=self.start,
            auto_stop_at=deadline,
            notify_on_auto_stop=True,
        )

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda _: self._run_in_connection(
                        lambda: stop_expired_timers(now=deadline + timedelta(seconds=1))
                    ),
                    range(2),
                )
            )

        session.refresh_from_db()
        self.assertEqual(sum(len(result) for result in results), 1)
        self.assertEqual(session.end_time, deadline)
        self.assertEqual(
            NotificationEvent.objects.filter(event_type="auto_stop", session=session).count(),
            1,
        )
