from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from unittest import mock

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from core.models import (
    NotificationEvent,
    NotificationPreference,
    Projects,
    PushSubscription,
    ScheduledReminder,
    Sessions,
    TimerReminder,
)
from core.services import reminder_dispatcher
from core.services.reminder_dispatcher import (
    next_dispatch_at,
    should_start_dispatcher,
)


class ShouldStartDispatcherTests(SimpleTestCase):

    def test_management_commands_do_not_start_the_thread(self):
        for argv in (
            ["manage.py", "test"],
            ["manage.py", "migrate"],
            ["manage.py", "check"],
            ["manage.py", "dispatch_timer_reminders", "--once"],
            ["manage.py"],
        ):
            with self.subTest(argv=argv):
                self.assertFalse(
                    should_start_dispatcher(argv, {"RUN_MAIN": "true"}, enabled=True)
                )


    def test_gunicorn_defers_startup_to_its_worker_hook(self):
        for argv0 in ("gunicorn", "/app/.venv/bin/gunicorn"):
            with self.subTest(argv0=argv0):
                self.assertFalse(
                    should_start_dispatcher(
                        [argv0, "AutumnWeb.wsgi:application"], {}, enabled=True
                    )
                )


class HistoryCleanupSchedulingTests(SimpleTestCase):
    def setUp(self):
        reminder_dispatcher._last_history_cleanup_monotonic = None

    def tearDown(self):
        reminder_dispatcher._last_history_cleanup_monotonic = None

    def test_cleanup_is_attempted_once_per_day(self):
        with mock.patch(
            "core.services.notification_retention.cleanup_notification_history"
        ) as cleanup, mock.patch.object(
            reminder_dispatcher.time, "monotonic", side_effect=[100.0, 200.0]
        ):
            reminder_dispatcher._maybe_cleanup_notification_history()
            reminder_dispatcher._maybe_cleanup_notification_history()

        cleanup.assert_called_once_with()


class DispatchOnceTests(SimpleTestCase):
    def test_locked_pass_runs_and_releases_the_lock(self):
        with mock.patch.object(
            reminder_dispatcher, "run_dispatch_pass", return_value=(0, [], 0)
        ) as one_pass, mock.patch(
            "django.core.cache.cache.add", return_value=True
        ), mock.patch(
            "django.core.cache.cache.get", return_value=None
        ), mock.patch(
            "django.core.cache.cache.delete"
        ), mock.patch.object(
            reminder_dispatcher, "_maybe_cleanup_notification_history"
        ):
            self.assertTrue(reminder_dispatcher._dispatch_once())
        one_pass.assert_called_once()

    def test_pass_is_skipped_when_the_lock_is_held(self):
        with mock.patch.object(
            reminder_dispatcher, "run_dispatch_pass"
        ) as one_pass, mock.patch("django.core.cache.cache.add", return_value=False):
            self.assertFalse(reminder_dispatcher._dispatch_once())
        one_pass.assert_not_called()


class DeadlinePlanningTests(SimpleTestCase):


    def test_due_deadline_dispatches_and_requests_immediate_rescan(self):
        now = datetime(2026, 9, 2, 10, tzinfo=dt_timezone.utc)
        with mock.patch.object(
            reminder_dispatcher, "next_dispatch_at", return_value=now
        ), mock.patch.object(
            reminder_dispatcher, "_dispatch_once", return_value=True
        ) as dispatch, mock.patch.object(
            reminder_dispatcher, "_maybe_cleanup_notification_history"
        ):
            self.assertIsNone(reminder_dispatcher._dispatch_step(now=now))

        dispatch.assert_called_once_with()


class PersistedDeadlineTests(TestCase):
    def setUp(self):
        reminder_dispatcher._wake_event.clear()
        self.user = User.objects.create_user(
            "dispatcher-deadlines", email="dispatcher@example.test"
        )
        self.project = Projects.objects.create(user=self.user, name="Dispatch work")
        self.now = datetime(2026, 9, 2, 10, tzinfo=dt_timezone.utc)

    def tearDown(self):
        reminder_dispatcher._wake_event.clear()

    def session(self, **overrides):
        values = {
            "user": self.user,
            "project": self.project,
            "start_time": self.now - timedelta(hours=1),
        }
        values.update(overrides)
        return Sessions.objects.create(**values)

    def event(self, **overrides):
        values = {
            "dedupe_key": f"deadline-event-{NotificationEvent.objects.count()}",
            "event_type": "reminder",
            "user": self.user,
            "payload": {},
            "scheduled_at": self.now,
        }
        values.update(overrides)
        return NotificationEvent.objects.create(**values)

    def subscription(self):
        return PushSubscription.objects.create(
            user=self.user,
            endpoint="https://fcm.googleapis.com/dispatcher-test",
            p256dh="key",
            auth="auth",
        )

    def test_startup_scan_finds_earliest_timer_and_proactive_deadline(self):
        session = self.session(auto_stop_at=self.now + timedelta(minutes=8))
        TimerReminder.objects.create(
            session=session,
            mode="after",
            next_fire_at=self.now + timedelta(minutes=7),
        )
        ScheduledReminder.objects.create(
            user=self.user,
            project=self.project,
            cadence="once",
            timezone="Europe/Prague",
            anchor_date=date(2026, 9, 2),
            anchor_time=time(12, 6),
            next_fire_at=self.now + timedelta(minutes=6),
        )
        NotificationPreference.objects.create(
            user=self.user,
            commitment_checks_enabled=True,
            weekly_review_enabled=True,
            next_commitment_check_at=self.now + timedelta(minutes=5),
            next_weekly_review_at=self.now + timedelta(minutes=4),
        )

        self.assertEqual(
            next_dispatch_at(now=self.now), self.now + timedelta(minutes=4)
        )


    def test_pending_event_without_deliveries_is_due_immediately(self):
        self.event()

        self.assertEqual(next_dispatch_at(now=self.now), self.now)


    def test_cancelled_work_is_not_a_deadline(self):
        session = self.session()
        TimerReminder.objects.create(
            session=session,
            mode="after",
            active=False,
            next_fire_at=None,
            cancelled_at=self.now,
        )
        self.event(status="cancelled")

        self.assertIsNone(next_dispatch_at(now=self.now))

    def test_committed_new_and_changed_work_wakes_dispatcher(self):
        reminder_dispatcher._wake_event.clear()
        with self.captureOnCommitCallbacks(execute=True):
            session = self.session(auto_stop_at=self.now + timedelta(minutes=10))
        self.assertTrue(reminder_dispatcher._wake_event.is_set())

        reminder_dispatcher._wake_event.clear()
        with self.captureOnCommitCallbacks(execute=True):
            session.auto_stop_at = self.now
            session.save(update_fields=["auto_stop_at"])
        self.assertTrue(reminder_dispatcher._wake_event.is_set())
        self.assertEqual(next_dispatch_at(now=self.now), self.now)
