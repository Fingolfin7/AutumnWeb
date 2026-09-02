from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from unittest import mock

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings

from core.models import (
    NotificationDelivery,
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
    run_dispatch_pass,
    should_start_dispatcher,
    start_dispatcher_thread,
)


class ShouldStartDispatcherTests(SimpleTestCase):
    def test_disabled_never_starts(self):
        self.assertFalse(
            should_start_dispatcher(
                ["manage.py", "runserver"], {"RUN_MAIN": "true"}, enabled=False
            )
        )

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

    def test_runserver_only_starts_in_the_autoreload_child(self):
        self.assertFalse(
            should_start_dispatcher(["manage.py", "runserver"], {}, enabled=True)
        )
        self.assertTrue(
            should_start_dispatcher(
                ["manage.py", "runserver"], {"RUN_MAIN": "true"}, enabled=True
            )
        )

    def test_runserver_noreload_starts_without_run_main(self):
        self.assertTrue(
            should_start_dispatcher(
                ["manage.py", "runserver", "--noreload"], {}, enabled=True
            )
        )

    def test_wsgi_servers_start_the_thread(self):
        for argv0 in (
            "gunicorn",
            "/app/.venv/bin/gunicorn",
            "uvicorn",
            "daphne",
        ):
            with self.subTest(argv0=argv0):
                self.assertTrue(
                    should_start_dispatcher(
                        [argv0, "AutumnWeb.wsgi:application"], {}, enabled=True
                    )
                )

    def test_unknown_program_defaults_to_false(self):
        self.assertFalse(should_start_dispatcher(["python", "-c", "x"], {}, enabled=True))
        self.assertFalse(should_start_dispatcher([], {}, enabled=True))


class RunDispatchPassTests(SimpleTestCase):
    def test_pass_runs_the_three_steps_and_returns_the_triple(self):
        events = [object(), object()]
        with self.assertLogs(
            "core.services.reminder_dispatcher", level="INFO"
        ) as captured:
            with mock.patch(
                "core.utils.stop_expired_timers", return_value=[object()]
            ) as stop, mock.patch(
                "core.services.reminders.claim_due_reminders", return_value=events
            ) as claim, mock.patch(
                "core.services.proactive_notifications.claim_due_proactive_notifications",
                return_value=[],
            ) as proactive_claim, mock.patch(
                "core.services.push.flush_outbox", return_value=3
            ) as flush:
                result = run_dispatch_pass(limit=7)

        self.assertEqual(result, (1, events, 3))
        stop.assert_called_once()
        self.assertEqual(claim.call_args.kwargs["limit"], 7)
        self.assertEqual(proactive_claim.call_args.kwargs["limit"], 5)
        self.assertEqual(flush.call_args.kwargs["limit"], 7)
        # Every step shares the single "now" instant of the pass.
        self.assertEqual(
            stop.call_args.kwargs["now"], claim.call_args.kwargs["now"]
        )
        self.assertEqual(
            stop.call_args.kwargs["now"], proactive_claim.call_args.kwargs["now"]
        )
        self.assertEqual(
            stop.call_args.kwargs["now"], flush.call_args.kwargs["now"]
        )
        self.assertIn(
            "notification_dispatch_pass stopped=1 claimed=2 outbox_flushed=3",
            captured.output[0],
        )


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
        ):
            self.assertTrue(reminder_dispatcher._dispatch_once())
        one_pass.assert_called_once()

    def test_pass_is_skipped_when_the_lock_is_held(self):
        with mock.patch.object(
            reminder_dispatcher, "run_dispatch_pass"
        ) as one_pass, mock.patch("django.core.cache.cache.add", return_value=False):
            self.assertFalse(reminder_dispatcher._dispatch_once())
        one_pass.assert_not_called()

    def test_broken_cache_skips_the_pass_instead_of_raising(self):
        with mock.patch.object(
            reminder_dispatcher, "run_dispatch_pass"
        ) as one_pass, mock.patch(
            "django.core.cache.cache.add", side_effect=RuntimeError("cache down")
        ):
            self.assertFalse(reminder_dispatcher._dispatch_once())
        one_pass.assert_not_called()


class DeadlinePlanningTests(SimpleTestCase):
    @override_settings(PUSH_DISPATCH_SAFETY_RESCAN_SECONDS=900)
    def test_idle_step_sleeps_for_safety_rescan_without_dispatching(self):
        now = datetime(2026, 9, 2, 10, tzinfo=dt_timezone.utc)
        with mock.patch.object(
            reminder_dispatcher, "next_dispatch_at", return_value=None
        ) as scan, mock.patch.object(reminder_dispatcher, "_dispatch_once") as dispatch:
            wait_seconds = reminder_dispatcher._dispatch_step(now=now)

        self.assertEqual(wait_seconds, 900)
        scan.assert_called_once_with(now=now)
        dispatch.assert_not_called()

    @override_settings(
        PUSH_DISPATCH_SAFETY_RESCAN_SECONDS=900,
        PUSH_DISPATCH_INTERVAL_SECONDS=15,
    )
    def test_future_deadline_is_respected_and_legacy_interval_is_ignored(self):
        now = datetime(2026, 9, 2, 10, tzinfo=dt_timezone.utc)
        deadline = now + timedelta(seconds=125)
        with mock.patch.object(
            reminder_dispatcher, "next_dispatch_at", return_value=deadline
        ), mock.patch.object(reminder_dispatcher, "_dispatch_once") as dispatch:
            wait_seconds = reminder_dispatcher._dispatch_step(now=now)

        self.assertEqual(wait_seconds, 125)
        dispatch.assert_not_called()

    def test_due_deadline_dispatches_and_requests_immediate_rescan(self):
        now = datetime(2026, 9, 2, 10, tzinfo=dt_timezone.utc)
        with mock.patch.object(
            reminder_dispatcher, "next_dispatch_at", return_value=now
        ), mock.patch.object(
            reminder_dispatcher, "_dispatch_once", return_value=True
        ) as dispatch:
            self.assertIsNone(reminder_dispatcher._dispatch_step(now=now))

        dispatch.assert_called_once_with()

    @override_settings(PUSH_DISPATCH_SAFETY_RESCAN_SECONDS=1)
    def test_safety_rescan_cannot_be_configured_below_five_minutes(self):
        self.assertEqual(reminder_dispatcher._safety_rescan_seconds(), 300)


class DispatchLoopTests(SimpleTestCase):
    def setUp(self):
        reminder_dispatcher._wake_event.clear()

    def tearDown(self):
        reminder_dispatcher._wake_event.clear()

    def test_waits_for_app_registry_before_scanning(self):
        with mock.patch(
            "django.apps.apps.ready_event.wait", side_effect=StopIteration
        ) as wait_until_ready, mock.patch.object(
            reminder_dispatcher, "_dispatch_step"
        ) as step:
            with self.assertRaises(StopIteration):
                reminder_dispatcher._dispatch_loop()

        wait_until_ready.assert_called_once_with()
        step.assert_not_called()

    def test_idle_timeout_rescans_without_a_fixed_pass(self):
        with mock.patch.object(
            reminder_dispatcher, "_dispatch_step", side_effect=[900, 900]
        ) as step, mock.patch.object(
            reminder_dispatcher._wake_event,
            "wait",
            side_effect=[False, StopIteration],
        ) as wait:
            with self.assertRaises(StopIteration):
                reminder_dispatcher._dispatch_loop()

        self.assertEqual(step.call_count, 2)
        self.assertEqual([call.args[0] for call in wait.call_args_list], [900, 900])

    def test_dispatcher_exception_backs_off_then_recovers(self):
        with mock.patch.object(
            reminder_dispatcher,
            "_dispatch_step",
            side_effect=[RuntimeError("database unavailable"), 900],
        ) as step, mock.patch.object(
            reminder_dispatcher._wake_event,
            "wait",
            side_effect=[True, StopIteration],
        ) as wait, self.assertLogs(
            "core.services.reminder_dispatcher", level="WARNING"
        ):
            with self.assertRaises(StopIteration):
                reminder_dispatcher._dispatch_loop()

        self.assertEqual(step.call_count, 2)
        self.assertEqual(wait.call_args_list[0].args[0], 15)
        self.assertEqual(wait.call_args_list[1].args[0], 900)


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

    def test_idle_deadline_scan_is_one_database_query(self):
        with self.assertNumQueries(1):
            self.assertIsNone(next_dispatch_at(now=self.now))

    def test_pending_event_without_deliveries_is_due_immediately(self):
        self.event()

        self.assertEqual(next_dispatch_at(now=self.now), self.now)

    def test_pending_delivery_retry_and_processing_lease_are_deadlines(self):
        subscription = self.subscription()
        retry_event = self.event(dedupe_key="retry-event")
        NotificationDelivery.objects.create(
            event=retry_event,
            subscription=subscription,
            status="pending",
            next_attempt_at=self.now + timedelta(minutes=3),
        )
        lease_event = self.event(dedupe_key="lease-event")
        NotificationDelivery.objects.create(
            event=lease_event,
            subscription=subscription,
            status="processing",
            lease_until=self.now + timedelta(minutes=2),
        )

        self.assertEqual(
            next_dispatch_at(now=self.now), self.now + timedelta(minutes=2)
        )

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


class StartDispatcherThreadTests(SimpleTestCase):
    def setUp(self):
        self.addCleanup(setattr, reminder_dispatcher, "_thread", None)
        reminder_dispatcher._thread = None

    def test_repeated_starts_create_a_single_thread(self):
        with mock.patch.object(reminder_dispatcher, "threading") as threading_mod:
            first = start_dispatcher_thread()
            second = start_dispatcher_thread()

        self.assertIs(first, second)
        threading_mod.Thread.assert_called_once()
        first.start.assert_called_once()
        self.assertTrue(threading_mod.Thread.call_args.kwargs["daemon"])
