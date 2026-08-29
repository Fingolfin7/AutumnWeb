from unittest import mock

from django.test import SimpleTestCase, override_settings

from core.services import reminder_dispatcher
from core.services.reminder_dispatcher import (
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
        with mock.patch(
            "core.utils.stop_expired_timers", return_value=[object()]
        ) as stop, mock.patch(
            "core.services.reminders.claim_due_reminders", return_value=events
        ) as claim, mock.patch(
            "core.services.push.flush_outbox", return_value=3
        ) as flush:
            result = run_dispatch_pass(limit=7)

        self.assertEqual(result, (1, events, 3))
        stop.assert_called_once()
        self.assertEqual(claim.call_args.kwargs["limit"], 7)
        self.assertEqual(flush.call_args.kwargs["limit"], 7)
        # Every step shares the single "now" instant of the pass.
        self.assertEqual(
            stop.call_args.kwargs["now"], claim.call_args.kwargs["now"]
        )
        self.assertEqual(
            stop.call_args.kwargs["now"], flush.call_args.kwargs["now"]
        )


class DispatchOnceTests(SimpleTestCase):
    @override_settings(PUSH_DISPATCH_INTERVAL_SECONDS=15.0)
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
