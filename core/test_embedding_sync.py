"""Background embedding after edits: queue timing, triggers and the sync itself.

OpenAI is always mocked (see core.test_semantic_search). Tests never start the
sync thread: the queue is driven with a fake clock, and triggers are observed
by patching ``request_sync``.
"""

import threading
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import ProjectEmbedding, Projects, SessionEmbedding, Sessions, SubProjects
from core.services import embedding_sync
from core.services.embedding_sync import (
    EDIT_DELAY_SECONDS,
    FAILURE_BACKOFF_SECONDS,
    FAILURE_RETRIES,
    SEARCH_RECHECK_SECONDS,
    SyncQueue,
    is_web_process,
    sync_account,
)
from core.services.sessions import SessionMutationService
from core.test_semantic_search import FakeOpenAI, SemanticSearchTestCase


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class SyncQueueTests(SimpleTestCase):
    def setUp(self):
        self.clock = Clock()
        self.runs = []
        self.succeed = True
        self.queue = SyncQueue(self._run, clock=self.clock)

    def _run(self, user_id):
        self.runs.append(user_id)
        return self.succeed

    def _advance(self, seconds):
        self.clock.now += seconds
        self.queue.run_due()

    def test_a_burst_of_edits_becomes_one_run_after_the_delay(self):
        for _ in range(50):
            self.queue.request(7)
        self._advance(EDIT_DELAY_SECONDS - 1)
        self.assertEqual(self.runs, [])
        self._advance(1)
        self.assertEqual(self.runs, [7])
        self._advance(EDIT_DELAY_SECONDS)
        self.assertEqual(self.runs, [7])

    def test_accounts_are_queued_separately_and_run_in_order(self):
        self.queue.request(1)
        self.clock.now += 1
        self.queue.request(2)
        self._advance(EDIT_DELAY_SECONDS)
        self.assertEqual(self.runs, [1, 2])

    def test_an_edit_during_a_run_queues_another_run(self):
        def run(user_id):
            self.runs.append(user_id)
            if len(self.runs) == 1:
                queue.request(user_id)  # an edit lands while the sync works
            return True

        queue = SyncQueue(run, clock=self.clock)
        queue.request(7)
        self.clock.now += EDIT_DELAY_SECONDS
        queue.run_due()
        self.assertEqual(self.runs, [7])
        self.clock.now += EDIT_DELAY_SECONDS
        queue.run_due()
        self.assertEqual(self.runs, [7, 7])

    def test_a_failed_account_waits_out_the_backoff(self):
        self.succeed = False
        self.queue.request(7)
        self._advance(EDIT_DELAY_SECONDS)
        self.queue.request(7)
        self._advance(FAILURE_BACKOFF_SECONDS - 1)
        self.assertEqual(self.runs, [7])
        self.succeed = True
        self._advance(1)
        self.assertEqual(self.runs, [7, 7])
        # Success clears the backoff.
        self.queue.request(7)
        self._advance(EDIT_DELAY_SECONDS)
        self.assertEqual(self.runs, [7, 7, 7])

    def test_a_failed_sync_retries_on_its_own_a_few_times(self):
        self.succeed = False
        self.queue.request(7)
        self._advance(EDIT_DELAY_SECONDS)
        for _ in range(FAILURE_RETRIES + 2):
            self._advance(FAILURE_BACKOFF_SECONDS)
        self.assertEqual(self.runs, [7] * (1 + FAILURE_RETRIES))
        self.assertEqual(self.queue.pending(), {})
        # A new edit still gets its run, and success resets the count.
        self.succeed = True
        self.queue.request(7)
        self._advance(EDIT_DELAY_SECONDS)
        self.assertEqual(len(self.runs), 2 + FAILURE_RETRIES)

    def test_a_transient_failure_recovers_without_another_request(self):
        self.succeed = False
        self.queue.request(7)
        self._advance(EDIT_DELAY_SECONDS)
        self.succeed = True
        self._advance(FAILURE_BACKOFF_SECONDS)
        self.assertEqual(self.runs, [7, 7])
        self.assertEqual(self.queue.pending(), {})

    def test_an_edit_during_a_failing_run_waits_out_the_backoff(self):
        def run(user_id):
            self.runs.append(user_id)
            queue.request(user_id, delay=0)  # an edit lands while the sync fails
            return False

        queue = SyncQueue(run, clock=self.clock)
        queue.request(7)
        self.clock.now += EDIT_DELAY_SECONDS
        queue.run_due()
        self.clock.now += FAILURE_BACKOFF_SECONDS - 1
        queue.run_due()
        self.assertEqual(self.runs, [7])
        self.clock.now += 1
        queue.run_due()
        self.assertEqual(self.runs, [7, 7])

    def test_a_failed_sync_does_not_count_as_a_recheck(self):
        self.succeed = False
        self.queue.request(7)
        self._advance(EDIT_DELAY_SECONDS)
        self.succeed = True
        self._advance(FAILURE_BACKOFF_SECONDS)  # the automatic retry succeeds
        self.queue.request(7, recheck=True)
        self._advance(EDIT_DELAY_SECONDS)
        self.assertEqual(self.runs, [7, 7])  # checked by the retry, so skipped

        queue = SyncQueue(lambda user_id: self.runs.append(user_id) or False, clock=self.clock)
        self.runs.clear()
        for _ in range(FAILURE_RETRIES + 1):
            queue.request(7)
            self.clock.now += FAILURE_BACKOFF_SECONDS + EDIT_DELAY_SECONDS
            queue.run_due()
        runs = len(self.runs)
        queue.request(7, recheck=True)  # never succeeded: a search still asks
        self.clock.now += FAILURE_BACKOFF_SECONDS + EDIT_DELAY_SECONDS
        queue.run_due()
        self.assertEqual(len(self.runs), runs + 1)

    def test_a_search_rechecks_an_account_at_most_every_window(self):
        self.queue.request(7, recheck=True)  # never checked: runs
        self._advance(EDIT_DELAY_SECONDS)
        self.queue.request(7, recheck=True)
        self._advance(SEARCH_RECHECK_SECONDS - 1)
        self.queue.request(7, recheck=True)
        self._advance(EDIT_DELAY_SECONDS)
        self.assertEqual(self.runs, [7])
        self.queue.request(7, recheck=True)  # the window has passed
        self._advance(EDIT_DELAY_SECONDS)
        self.assertEqual(self.runs, [7, 7])

    def test_an_edit_is_never_dropped_by_the_recheck_window(self):
        self.queue.request(7)
        self._advance(EDIT_DELAY_SECONDS)
        self.queue.request(7)
        self._advance(EDIT_DELAY_SECONDS)
        self.assertEqual(self.runs, [7, 7])

    def test_the_thread_wakes_for_a_new_request(self):
        done = threading.Event()
        queue = SyncQueue(lambda user_id: done.set() or True)
        threading.Thread(target=queue.serve_forever, daemon=True).start()
        queue.request(7, delay=0)
        self.assertTrue(done.wait(5))


class WebProcessTests(SimpleTestCase):
    def test_only_request_serving_processes_qualify(self):
        self.assertTrue(is_web_process(["/opt/venv/bin/gunicorn", "AutumnWeb.wsgi"], {}))
        self.assertTrue(is_web_process(["uvicorn", "AutumnWeb.asgi:application"], {}))
        self.assertTrue(is_web_process(["manage.py", "runserver", "--noreload"], {}))
        self.assertTrue(is_web_process(["manage.py", "runserver"], {"RUN_MAIN": "true"}))
        self.assertFalse(is_web_process(["manage.py", "runserver"], {}))
        self.assertFalse(is_web_process(["manage.py", "test"], {}))
        self.assertFalse(is_web_process(["manage.py", "embed_sessions"], {}))
        self.assertFalse(is_web_process([], {}))

    def test_tests_never_queue_or_start_a_thread(self):
        with mock.patch.object(embedding_sync, "_get_queue") as get_queue:
            embedding_sync.request_sync(1)
        get_queue.assert_not_called()

    @override_settings(SEMANTIC_SYNC_ON_WRITE=False)
    def test_setting_turns_it_off(self):
        with mock.patch.object(embedding_sync, "is_web_process", return_value=True):
            self.assertFalse(embedding_sync.background_sync_enabled())


class SyncAccountTests(SemanticSearchTestCase):
    def test_embeds_whatever_is_missing_or_stale(self):
        self.assertTrue(sync_account(self.user.pk))
        self.assertEqual(SessionEmbedding.objects.filter(session__user=self.user).count(), 3)
        self.assertEqual(ProjectEmbedding.objects.filter(project__user=self.user).count(), 2)
        self.plants.note = "Pruned the orchard"
        self.plants.save()
        FakeOpenAI.instances = []
        self.assertTrue(sync_account(self.user.pk))
        self.assertEqual(FakeOpenAI.all_inputs(), [[mock.ANY]])
        self.assertIn("Pruned the orchard", FakeOpenAI.all_inputs()[0][0])

    def test_uses_the_accounts_own_key_with_sync_timeouts(self):
        sync_account(self.user.pk)
        client = FakeOpenAI.instances[0]
        self.assertEqual(client.api_key, "user-key")
        self.assertEqual(client.max_retries, 2)

    def test_accounts_without_ai_or_key_are_left_alone(self):
        off = self._user("off-user", "off-key", ai=False)
        keyless = self._user("keyless-user", None)
        for user in (off, keyless):
            self.assertTrue(sync_account(user.pk))
        self.assertTrue(sync_account(999999))
        self.assertEqual(FakeOpenAI.instances, [])

    def test_a_provider_failure_reports_false_without_raising(self):
        FakeOpenAI.fail = True
        with self.assertLogs("core.services.embedding_sync", "WARNING") as logs:
            self.assertFalse(sync_account(self.user.pk))
        self.assertIn("semantic_sync_failed", logs.output[0])
        self.assertNotIn("Watered", "".join(logs.output))


@mock.patch.object(embedding_sync, "background_sync_enabled", return_value=True)
@mock.patch.object(embedding_sync, "request_sync")
class TriggerTests(SemanticSearchTestCase):
    def _requested(self, request_sync, action):
        request_sync.reset_mock()
        with self.captureOnCommitCallbacks(execute=True):
            action()
        return [call.args[0] for call in request_sync.call_args_list]

    def test_completed_session_edits_request_a_sync(self, request_sync, _enabled):
        def edit():
            self.plants.note = "Pruned the orchard"
            self.plants.save()

        self.assertEqual(self._requested(request_sync, edit), [self.user.pk])

    def test_running_timers_do_not(self, request_sync, _enabled):
        def start():
            Sessions.objects.create(
                user=self.user, project=self.garden, start_time=timezone.now(), note="Weeding"
            )

        self.assertEqual(self._requested(request_sync, start), [])

    def test_project_and_subproject_writes_request_a_sync(self, request_sync, _enabled):
        def rename():
            self.identity.name = "Accounts"
            self.identity.save()

        self.assertEqual(self._requested(request_sync, rename), [self.user.pk])
        self.assertEqual(self._requested(request_sync, self.tokens.delete), [self.user.pk])
        self.assertEqual(
            self._requested(
                request_sync,
                lambda: SubProjects.objects.create(user=self.user, parent_project=self.garden, name="Beds"),
            ),
            [self.user.pk],
        )

    def test_nothing_is_requested_until_the_transaction_commits(self, request_sync, _enabled):
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            self.plants.note = "Pruned the orchard"
            self.plants.save()
            request_sync.assert_not_called()
        for callback in callbacks:
            callback()
        request_sync.assert_called_once_with(self.user.pk)

    def test_turning_on_ai_with_a_key_requests_a_sync(self, request_sync, _enabled):
        newcomer = self._user("newcomer", None, ai=False)

        def enable():
            newcomer.profile.ai_features_enabled = True
            newcomer.profile.set_api_key("openai", "new-key")
            newcomer.profile.save()

        self.assertEqual(self._requested(request_sync, enable), [newcomer.pk])

        def disable():
            newcomer.profile.ai_features_enabled = False
            newcomer.profile.save()

        self.assertEqual(self._requested(request_sync, disable), [])

    def test_api_description_update_requests_a_sync(self, request_sync, _enabled):
        def update():
            response = self.client.patch(
                f"/api/v2/projects/{self.garden.pk}",
                {"description": "Fruit trees and beds"},
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200, response.content)

        self.assertIn(self.user.pk, self._requested(request_sync, update))

    def test_an_auto_stopped_timer_requests_a_sync(self, request_sync, _enabled):
        start = timezone.now() - timedelta(hours=2)
        running = Sessions.objects.create(
            user=self.user,
            project=self.garden,
            start_time=start,
            auto_stop_at=start + timedelta(hours=1),
            note="Weeding",
        )

        def stop():
            self.assertIsNotNone(SessionMutationService.auto_stop_session(running.pk))

        self.assertEqual(self._requested(request_sync, stop), [self.user.pk])


class SearchRecheckTests(SemanticSearchTestCase):
    def test_a_related_search_asks_for_a_recheck(self):
        with mock.patch("core.services.semantic_search.request_sync") as request_sync:
            self.client.get(reverse("api_v2:sessions"), {"search": "login", "related": "true"})
        request_sync.assert_called_with(self.user.pk, recheck=True)

    def test_accounts_without_ai_do_not(self):
        self.user.profile.ai_features_enabled = False
        self.user.profile.save()
        cache.clear()
        with mock.patch("core.services.semantic_search.request_sync") as request_sync:
            self.client.get(reverse("api_v2:sessions"), {"search": "login", "related": "true"})
        request_sync.assert_not_called()

    def test_every_api_surface_that_searches_related_asks_for_a_recheck(self):
        surfaces = (
            ("api_v2:projects", {}),
            ("api_v2:report-totals", {}),
            ("api_v2:report-charts", {"chart_type": "pie"}),
            ("api_v2:export", {}),
        )
        for name, extra in surfaces:
            with self.subTest(name=name):
                cache.clear()
                with mock.patch("core.services.semantic_search.request_sync") as request_sync:
                    response = self.client.get(
                        reverse(name), {"search": "login", "related": "true", **extra}
                    )
                self.assertEqual(response.status_code, 200, response.content)
                request_sync.assert_called_with(self.user.pk, recheck=True)
