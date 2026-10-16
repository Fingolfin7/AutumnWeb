"""Background embedding after edits: queue timing, triggers and the sync itself.

OpenAI is always mocked (see core.test_semantic_search). Tests never start the
sync thread: the queue is driven with a fake clock, and triggers are observed
by patching ``request_sync``.
"""

from unittest import mock

from django.test import SimpleTestCase
from django.urls import reverse

from core.models import ProjectEmbedding, SessionEmbedding, SubProjects
from core.services import embedding_sync
from core.services.embedding_sync import (
    EDIT_DELAY_SECONDS,
    FAILURE_BACKOFF_SECONDS,
    SEARCH_RECHECK_SECONDS,
    SyncQueue,
    sync_account,
)
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


    def test_a_transient_failure_recovers_without_another_request(self):
        self.succeed = False
        self.queue.request(7)
        self._advance(EDIT_DELAY_SECONDS)
        self.succeed = True
        self._advance(FAILURE_BACKOFF_SECONDS)
        self.assertEqual(self.runs, [7, 7])
        self.assertEqual(self.queue.pending(), {})


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


class WebProcessTests(SimpleTestCase):

    def test_tests_never_queue_or_start_a_thread(self):
        with mock.patch.object(embedding_sync, "_get_queue") as get_queue:
            embedding_sync.request_sync(1)
        get_queue.assert_not_called()


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


class SearchRecheckTests(SemanticSearchTestCase):
    def test_a_related_search_asks_for_a_recheck(self):
        with mock.patch("core.services.semantic_search.request_sync") as request_sync:
            self.client.get(reverse("api_v2:sessions"), {"search": "login", "related": "true"})
        request_sync.assert_called_with(self.user.pk, recheck=True)
