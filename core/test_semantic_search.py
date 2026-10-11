"""Meaning-based Sessions search: sync, isolation, filters and fallbacks.

OpenAI is always mocked. The fake model maps words to a few concept axes, so
"sign-in failure" and "repaired OAuth token refresh" land close together
while unrelated notes stay below the similarity cutoff.
"""

from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Context,
    Projects,
    RecommendationUsage,
    SessionEmbedding,
    Sessions,
    SubProjects,
    Tag,
)
from core.services import semantic_search
from core.services.semantic_search import (
    DIMENSIONS,
    MODEL,
    decode_vector,
    encode_vector,
    load_vectors,
    reciprocal_rank_fusion,
    session_text,
)

CONCEPTS = {
    0: ("sign-in", "login", "oauth", "auth"),
    1: ("charged", "invoice", "billing", "payment"),
    2: ("garden", "plants", "watered", "orchard"),
}


def fake_vector(text):
    text = text.lower()
    vector = [0.0] * DIMENSIONS
    for axis, words in CONCEPTS.items():
        vector[axis] = float(sum(word in text for word in words))
    vector[DIMENSIONS - 1] = 0.1  # shared baseline: nothing is orthogonal
    return vector


class FakeOpenAI:
    """Stands in for openai.OpenAI; records each client and call."""

    instances = []

    def __init__(self, *, api_key, timeout, max_retries):
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.calls = []
        self.fail = False
        self.embeddings = SimpleNamespace(create=self._create)
        FakeOpenAI.instances.append(self)

    def _create(self, *, model, input, dimensions):
        self.calls.append(list(input))
        if FakeOpenAI.fail:
            raise TimeoutError("provider timed out")
        assert model == MODEL and dimensions == DIMENSIONS
        return SimpleNamespace(
            data=[
                SimpleNamespace(index=i, embedding=fake_vector(text))
                for i, text in reversed(list(enumerate(input)))
            ],
            usage=SimpleNamespace(prompt_tokens=10 * len(input), total_tokens=10 * len(input)),
        )

    @classmethod
    def all_inputs(cls):
        return [batch for client in cls.instances for batch in client.calls]


FakeOpenAI.fail = False


class SemanticSearchTestCase(TestCase):
    def setUp(self):
        cache.clear()
        FakeOpenAI.instances = []
        FakeOpenAI.fail = False
        patcher = mock.patch("openai.OpenAI", FakeOpenAI)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.user = self._user("semantic-user", "user-key")
        self.work = Context.objects.create(user=self.user, name="Work")
        self.home = Context.objects.create(user=self.user, name="Home")
        self.security = Tag.objects.create(user=self.user, name="Security")
        self.identity = Projects.objects.create(user=self.user, name="Identity", context=self.work)
        self.identity.tags.add(self.security)
        self.garden = Projects.objects.create(user=self.user, name="Garden", context=self.home)
        self.tokens = SubProjects.objects.create(user=self.user, parent_project=self.identity, name="Tokens")

        self.oauth = self._session(self.identity, "Repaired OAuth token refresh", days_ago=10)
        self.oauth.subprojects.add(self.tokens)
        self.plants = self._session(self.garden, "Watered the plants", days_ago=2)
        self.failure_note = self._session(self.identity, "Investigated sign-in failure reports", days_ago=1)
        self.client.force_login(self.user)

    def _user(self, username, key, *, ai=True):
        user = User.objects.create_user(username, email=f"{username}@example.com", password="pw")
        user.profile.ai_features_enabled = ai
        if key:
            user.profile.set_api_key("openai", key)
        user.profile.save()
        return user

    def _session(self, project, note, *, days_ago=1, user=None):
        end = timezone.now() - timedelta(days=days_ago)
        return Sessions.objects.create(
            user=user or self.user,
            project=project,
            start_time=end - timedelta(minutes=30),
            end_time=end,
            note=note,
        )

    def _sync(self, *args):
        out = StringIO()
        call_command("embed_sessions", *args, stdout=out, stderr=StringIO())
        return out.getvalue()

    def _search(self, term, **params):
        return self.client.get(reverse("sessions"), {"search": term, **params})

    def _related(self, term, **params):
        return [session.pk for session in self._search(term, **params).context["related_sessions"]]


class RelatedSessionsTests(SemanticSearchTestCase):
    def test_paraphrase_missed_by_keywords_is_related(self):
        self._sync()
        response = self._search("sign-in failure")

        # Keyword results are exactly what they were; only the note that says
        # the words matches them.
        self.assertEqual([s.pk for s in response.context["object_list"]], [self.failure_note.pk])
        self.assertEqual([s.pk for s in response.context["related_sessions"]], [self.oauth.pk])
        self.assertContains(response, 'aria-label="Related sessions"')
        self.assertContains(response, "Repaired OAuth token refresh")

    def test_unrelated_query_shows_no_related_section(self):
        self._sync()
        response = self._search("nonexistent lighthouse project")
        self.assertEqual(response.context["related_sessions"], [])
        self.assertNotContains(response, "Related sessions")

    def test_related_only_on_first_page_and_list_is_unchanged(self):
        for day in range(10):
            self._session(self.identity, f"Sign-in failure triage {day}", days_ago=20 + day)
        self._sync()
        first = self._search("sign-in failure")
        self.assertTrue(first.context["is_paginated"])
        self.assertEqual(first.context["result_count"], 11)
        self.assertEqual([s.pk for s in first.context["related_sessions"]], [self.oauth.pk])
        second = self._search("sign-in failure", page=2)
        self.assertEqual(second.context["related_sessions"], [])

    def test_query_vector_is_cached(self):
        self._sync()
        calls = len(FakeOpenAI.all_inputs())
        self._search("sign-in failure")
        self._search("sign-in failure")
        self.assertEqual(len(FakeOpenAI.all_inputs()), calls + 1)

    def test_usage_is_recorded_with_estimated_cost(self):
        self._sync()
        self._search("sign-in failure")
        rows = RecommendationUsage.objects.filter(user=self.user, model=MODEL)
        self.assertEqual(rows.count(), 2)  # one sync batch, one query
        self.assertTrue(all(row.success and row.input_tokens for row in rows))
        self.assertTrue(all(row.estimated_cost_usd is not None for row in rows))


class IsolationTests(SemanticSearchTestCase):
    def test_other_accounts_sessions_never_appear(self):
        other = self._user("semantic-other", "other-key")
        foreign_project = Projects.objects.create(user=other, name="Foreign")
        foreign = self._session(foreign_project, "Fixed OAuth login sign-in", user=other)
        self._sync()
        self.assertTrue(SessionEmbedding.objects.filter(session=foreign).exists())

        self.assertNotIn(foreign.pk, self._related("sign-in failure"))

    def test_each_account_is_embedded_and_queried_with_its_own_key(self):
        other = self._user("semantic-keyed", "other-key")
        self._session(Projects.objects.create(user=other, name="Other"), "OAuth", user=other)
        self._sync()
        self.assertEqual({c.api_key for c in FakeOpenAI.instances}, {"user-key", "other-key"})
        for client in FakeOpenAI.instances:
            texts = [text for batch in client.calls for text in batch]
            owner = self.user if client.api_key == "user-key" else other
            expected = {
                session_text(s.project.name, [sp.name for sp in s.subprojects.all()], s.note)
                for s in Sessions.objects.filter(user=owner)
            }
            self.assertEqual(set(texts), expected)

        FakeOpenAI.instances = []
        self._search("sign-in failure")
        [query_client] = FakeOpenAI.instances
        self.assertEqual(query_client.api_key, "user-key")
        self.assertEqual(query_client.max_retries, 0)
        self.assertLessEqual(query_client.timeout, 5)


class FilterTests(SemanticSearchTestCase):
    def setUp(self):
        super().setUp()
        self._sync()

    def test_related_obeys_every_sessions_filter(self):
        old = (timezone.now() - timedelta(days=5)).date().isoformat()
        cases = (
            ({}, [self.oauth.pk]),
            ({"start_date": old}, []),
            ({"end_date": old}, [self.oauth.pk]),
            ({"context": str(self.home.pk)}, []),
            ({"context": str(self.work.pk)}, [self.oauth.pk]),
            ({"tags": str(self.security.pk)}, [self.oauth.pk]),
            ({"exclude_projects": str(self.identity.pk)}, []),
            ({"include_projects": str(self.garden.pk)}, []),
            ({"include_projects": str(self.identity.pk)}, [self.oauth.pk]),
            ({"note_snippet": "plants"}, []),
        )
        for params, expected in cases:
            with self.subTest(params=params):
                self.assertEqual(self._related("sign-in failure", **params), expected)

    def test_keyword_matches_are_not_repeated_as_related(self):
        # "oauth" matches the note by substring, so it is a keyword result.
        response = self._search("oauth")
        self.assertIn(self.oauth.pk, [s.pk for s in response.context["object_list"]])
        self.assertNotIn(self.oauth.pk, [s.pk for s in response.context["related_sessions"]])


class StalenessTests(SemanticSearchTestCase):
    def setUp(self):
        super().setUp()
        self._sync()
        FakeOpenAI.instances = []

    def _resynced_texts(self):
        FakeOpenAI.instances = []
        self._sync()
        return [text for batch in FakeOpenAI.all_inputs() for text in batch]

    def test_unchanged_sessions_are_skipped(self):
        self.assertEqual(self._resynced_texts(), [])

    def test_note_edit_is_stale_until_resynced(self):
        self.oauth.note = "Watered the orchard"
        self.oauth.save()
        # The old vector still says "auth", but it no longer describes the
        # session, so it is not offered.
        self.assertEqual(self._related("sign-in failure"), [])

        texts = self._resynced_texts()
        self.assertEqual(len(texts), 1)
        self.assertIn("Watered the orchard", texts[0])
        self.assertEqual(self._related("sign-in failure"), [])

    def test_project_rename_restales_its_sessions(self):
        Projects.objects.filter(pk=self.identity.pk).update(name="Identity Platform")
        texts = self._resynced_texts()
        self.assertEqual(len(texts), 2)
        self.assertTrue(all(text.startswith("Identity Platform\n") for text in texts))

    def test_subproject_rename_restales_its_sessions(self):
        SubProjects.objects.filter(pk=self.tokens.pk).update(name="Refresh tokens")
        texts = self._resynced_texts()
        self.assertEqual(texts, [session_text("Identity", ["Refresh tokens"], self.oauth.note)])

    def test_model_change_restales_everything(self):
        SessionEmbedding.objects.update(model="older-model")
        self.assertEqual(len(self._resynced_texts()), 3)


class FallbackTests(SemanticSearchTestCase):
    def test_ai_disabled_or_no_key_behaves_exactly_as_keyword_search(self):
        self._sync()
        FakeOpenAI.instances = []
        profile = self.user.profile
        for ai, key in ((False, "user-key"), (True, None)):
            with self.subTest(ai=ai, key=key):
                profile.ai_features_enabled = ai
                profile.set_api_key("openai", key)
                profile.save()
                response = self._search("sign-in failure")
                self.assertEqual([s.pk for s in response.context["object_list"]], [self.failure_note.pk])
                self.assertEqual(response.context["related_sessions"], [])
                self.assertNotContains(response, "Related sessions")
        self.assertEqual(FakeOpenAI.instances, [])

    def test_command_skips_accounts_without_ai_or_key(self):
        off = self._user("semantic-off", "off-key", ai=False)
        keyless = self._user("semantic-keyless", None)
        for user in (off, keyless):
            self._session(Projects.objects.create(user=user, name="P"), "note", user=user)
        self._sync()
        self.assertEqual({c.api_key for c in FakeOpenAI.instances}, {"user-key"})
        self.assertFalse(SessionEmbedding.objects.filter(session__user__in=[off, keyless]).exists())
        self.assertIn("skipped", self._sync("--username", "semantic-off"))

    def test_no_vectors_yet_means_no_provider_call(self):
        self._search("sign-in failure")
        self.assertEqual(FakeOpenAI.all_inputs(), [])

    def test_provider_failure_falls_back_to_keyword_results(self):
        self._sync()
        FakeOpenAI.fail = True
        with self.assertLogs("core.services.semantic_search", "WARNING"):
            response = self._search("sign-in failure")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([s.pk for s in response.context["object_list"]], [self.failure_note.pk])
        self.assertEqual(response.context["related_sessions"], [])
        failed = RecommendationUsage.objects.get(user=self.user, success=False)
        self.assertEqual(failed.error_category, "TimeoutError")

    def test_sync_failure_keeps_progress_and_reports(self):
        FakeOpenAI.fail = True
        with self.assertRaises(CommandError):
            call_command("embed_sessions", stdout=StringIO(), stderr=StringIO())
        self.assertFalse(SessionEmbedding.objects.exists())

    def test_dry_run_calls_nothing(self):
        out = self._sync("--dry-run")
        self.assertIn("3 to embed", out)
        self.assertEqual(FakeOpenAI.all_inputs(), [])
        self.assertFalse(SessionEmbedding.objects.exists())

    def test_limit_takes_newest_first_and_batches(self):
        self._sync("--limit", "2", "--batch-size", "1")
        self.assertEqual(len(FakeOpenAI.all_inputs()), 2)
        self.assertEqual(
            set(SessionEmbedding.objects.values_list("session_id", flat=True)),
            {self.plants.pk, self.failure_note.pk},
        )

    def test_active_sessions_are_not_embedded(self):
        Sessions.objects.create(user=self.user, project=self.identity, note="OAuth live")
        self._sync()
        self.assertEqual(SessionEmbedding.objects.count(), 3)


class VectorTests(TestCase):
    def test_memoryview_vectors_decode_like_bytes(self):
        data = encode_vector(fake_vector("oauth login"))
        self.assertEqual(list(decode_vector(memoryview(data))), list(decode_vector(data)))

    def test_load_vectors_accepts_postgres_memoryview_rows(self):
        good = encode_vector(fake_vector("oauth"))
        rows = [(1, "d1", memoryview(good)), (2, "d2", memoryview(b"short")), (3, "d3", good)]
        with mock.patch.object(semantic_search, "SessionEmbedding") as model:
            model.objects.filter.return_value.order_by.return_value.values_list.return_value = rows
            ids, digests, matrix = load_vectors(User(pk=1), Sessions.objects.none())
        self.assertEqual(ids, [1, 3])
        self.assertEqual(digests, {1: "d1", 3: "d3"})
        self.assertEqual(matrix.shape, (2, DIMENSIONS))

    def test_vectors_are_unit_length(self):
        vector = decode_vector(encode_vector(fake_vector("billing invoice")))
        self.assertAlmostEqual(float((vector * vector).sum()), 1.0, places=5)

    def test_long_notes_are_capped(self):
        text = session_text("P", ["b", "a", "a"], "x" * 10_000)
        self.assertTrue(text.startswith("P\na, b\n"))
        self.assertEqual(len(text), semantic_search.MAX_INPUT_CHARS)

    def test_reciprocal_rank_fusion(self):
        self.assertEqual(reciprocal_rank_fusion([[1, 2, 3], [3, 4]]), [3, 1, 2, 4])
        self.assertEqual(reciprocal_rank_fusion([[1], [2]]), [1, 2])
