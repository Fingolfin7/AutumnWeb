"""The similarity cutoff (Related slider, profile default, ?similarity=) and
word-by-word keyword search.

Uses the fake concept-axis model from test_semantic_search, so scores are
exact: "sign-in failure" scores ~1.0 against the OAuth note, ~0.41 against a
note that mixes login with billing and gardening, and ~0 against plants.
"""

from django.test import SimpleTestCase
from django.urls import reverse

from core.models import Projects, Sessions
from core.search import keyword_sessions, search_words
from core.services.semantic_search import (
    SIMILARITY_CEILING,
    SIMILARITY_FLOOR,
    RelatedOutcome,
    parse_similarity,
    related_session_ids,
)
from core.test_semantic_search import SemanticSearchTestCase


class SearchWordsTests(SimpleTestCase):
    def test_common_words_are_dropped(self):
        self.assertEqual(search_words("figured it out"), ["figured", "out"])

    def test_a_term_of_only_common_words_keeps_them(self):
        self.assertEqual(search_words("it is"), ["it", "is"])

    def test_quoted_phrases_stay_whole(self):
        self.assertEqual(search_words('fix the "login bug" today'), ["login bug", "fix", "today"])
        self.assertEqual(search_words('"figured it out"'), ["figured it out"])


class KeywordWordsTests(SemanticSearchTestCase):
    def test_every_word_must_appear_in_any_order_or_field(self):
        sessions = Sessions.objects.filter(user=self.user)
        # "refresh" is in the note; "tokens" is the subproject's name.
        self.assertEqual(
            list(keyword_sessions(sessions, "tokens refresh").values_list("pk", flat=True)),
            [self.oauth.pk],
        )
        self.assertFalse(keyword_sessions(sessions, "tokens watered").exists())

    def test_a_paraphrased_phrase_still_matches_by_its_words(self):
        note = self._session(self.identity, "Finally figured out the cache bug")
        sessions = Sessions.objects.filter(user=self.user)
        self.assertEqual(
            list(keyword_sessions(sessions, "figured it out").values_list("pk", flat=True)),
            [note.pk],
        )
        self.assertFalse(keyword_sessions(sessions, '"figured it out"').exists())


class ParseSimilarityTests(SimpleTestCase):
    def test_bounds_and_rounding(self):
        self.assertIsNone(parse_similarity(None))
        self.assertIsNone(parse_similarity(" "))
        self.assertEqual(parse_similarity("0.374"), 0.37)
        self.assertEqual(parse_similarity(SIMILARITY_FLOOR), SIMILARITY_FLOOR)
        self.assertEqual(parse_similarity(SIMILARITY_CEILING), SIMILARITY_CEILING)
        for bad in ("0.2", "0.61", "nan", "loose"):
            with self.assertRaises(ValueError):
                parse_similarity(bad)


class CutoffTests(SemanticSearchTestCase):
    """The mixed note scores ~0.41: related below the 0.45 default only."""

    def setUp(self):
        super().setUp()
        self.mixed = self._session(self.identity, "Login for the invoice, watered plants")
        self._sync()

    def _ids(self, **kwargs):
        sessions = Sessions.objects.filter(user=self.user, end_time__isnull=False)
        keyword = keyword_sessions(sessions, "sign-in failure")
        return related_session_ids(
            self.user, sessions, keyword, "sign-in failure", limit=None, **kwargs
        )

    def test_default_cutoff_leaves_the_weaker_match_out(self):
        self.assertEqual(self._ids(), [self.oauth.pk])

    def test_a_lower_cutoff_lets_it_in_best_first(self):
        self.assertEqual(self._ids(cutoff=0.40), [self.oauth.pk, self.mixed.pk])


    def test_collected_scores_count_every_slider_step(self):
        outcome = RelatedOutcome(collect_scores=True)
        self.assertEqual(self._ids(outcome=outcome), [self.oauth.pk])
        self.assertEqual(outcome.cutoff, 0.45)
        self.assertEqual(len(outcome.scores), 2)
        self.assertGreater(outcome.best, 0.99)
        counts = outcome.counts()
        self.assertEqual(len(counts), 36)
        self.assertEqual(counts[0], 2)  # 0.25
        self.assertEqual(counts[15], 2)  # 0.40
        self.assertEqual(counts[20], 1)  # 0.45
        self.assertEqual(counts[-1], 1)  # 0.60


class ApiSimilarityTests(SemanticSearchTestCase):
    def setUp(self):
        super().setUp()
        self.mixed = self._session(self.identity, "Login for the invoice, watered plants")
        self._sync()

    def _get(self, name, **params):
        return self.client.get(reverse(name), {"search": "sign-in failure", "related": "true", **params})

    def test_sessions_take_and_echo_the_cutoff(self):
        default = self._get("api_v2:sessions")
        self.assertEqual(default["X-Autumn-Related-Similarity"], "0.45")
        self.assertNotIn(self.mixed.pk, [row["id"] for row in default.json()["sessions"]])
        loose = self._get("api_v2:sessions", similarity="0.40")
        self.assertEqual(loose["X-Autumn-Related-Similarity"], "0.40")
        self.assertIn(self.mixed.pk, [row["id"] for row in loose.json()["sessions"]])

    def test_out_of_range_is_rejected(self):
        for name in ("api_v2:sessions", "api_v2:report-totals", "api_v2:projects"):
            response = self._get(name, similarity="0.9")
            self.assertEqual(response.status_code, 400, name)


class ProjectsRelatedPagingTests(SemanticSearchTestCase):
    def setUp(self):
        super().setUp()
        self.auth_projects = [
            Projects.objects.create(user=self.user, name=f"Auth service {n}", context=self.work)
            for n in range(6)
        ]
        self._sync()

    def _page(self, **params):
        response = self.client.get(
            reverse("api_v2:projects"),
            {"search": "sign-in failure", "related": "true", **params},
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response

    def test_every_related_project_is_reachable_by_paging(self):
        # Identity matches by keyword (its "sign-in failure" note), so it is a
        # direct match, not a related one: 7 in all, 6 of them related.
        first = self._page(limit=5)
        self.assertEqual(first.json()["total"], 7)
        self.assertEqual(first.json()["count"], 5)
        second = self._page(limit=5, offset=5)
        self.assertEqual(second.json()["count"], 2)
        shown = {row["id"] for row in first.json()["projects"] + second.json()["projects"]}
        self.assertEqual(shown, {p.pk for p in self.auth_projects} | {self.identity.pk})
