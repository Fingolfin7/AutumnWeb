"""The similarity cutoff (Related slider, profile default, ?similarity=) and
word-by-word keyword search.

Uses the fake concept-axis model from test_semantic_search, so scores are
exact: "sign-in failure" scores ~1.0 against the OAuth note, ~0.41 against a
note that mixes login with billing and gardening, and ~0 against plants.
"""

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.models import Projects, Sessions
from core.search import keyword_sessions, search_projects, search_words
from core.services.semantic_search import (
    SIMILARITY_CEILING,
    SIMILARITY_FLOOR,
    RelatedOutcome,
    min_similarity,
    parse_similarity,
    related_session_ids,
)
from core.test_semantic_search import SemanticSearchTestCase
from users.forms import ProfileUpdateForm


class SearchWordsTests(SimpleTestCase):
    def test_common_words_are_dropped(self):
        self.assertEqual(search_words("figured it out"), ["figured", "out"])

    def test_a_term_of_only_common_words_keeps_them(self):
        self.assertEqual(search_words("it is"), ["it", "is"])

    def test_quoted_phrases_stay_whole(self):
        self.assertEqual(search_words('fix the "login bug" today'), ["login bug", "fix", "today"])
        self.assertEqual(search_words('"figured it out"'), ["figured it out"])

    def test_edge_punctuation_and_repeats_are_dropped(self):
        self.assertEqual(search_words("AutumnWeb, backend!"), ["AutumnWeb", "backend"])
        self.assertEqual(search_words("Out out OUT"), ["Out"])

    def test_blank(self):
        self.assertEqual(search_words("   "), [])
        self.assertEqual(search_words(None), [])


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

    def test_projects_match_word_by_word(self):
        projects = Projects.objects.filter(user=self.user)
        # "identity" from the name, "refresh" from a session note.
        self.assertEqual(list(search_projects(projects, "refresh identity")), [self.identity])
        self.assertFalse(search_projects(projects, "refresh garden").exists())


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

    def test_profile_default_is_the_accounts_cutoff(self):
        self.user.profile.related_similarity = 0.40
        self.user.profile.save()
        self.assertEqual(min_similarity(self.user), 0.40)
        self.assertEqual(self._ids(), [self.oauth.pk, self.mixed.pk])

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

    def test_scores_are_not_collected_unless_asked(self):
        outcome = RelatedOutcome()
        self._ids(outcome=outcome)
        self.assertEqual(outcome.scores, [])


class SessionsPageSliderTests(SemanticSearchTestCase):
    def setUp(self):
        super().setUp()
        self.mixed = self._session(self.identity, "Login for the invoice, watered plants")
        self._sync()

    def test_similarity_param_sets_the_cutoff(self):
        self.assertEqual(self._related("sign-in failure"), [self.oauth.pk])
        self.assertEqual(
            self._related("sign-in failure", similarity="0.40"), [self.oauth.pk, self.mixed.pk]
        )

    def test_invalid_similarity_falls_back_to_the_default(self):
        self.assertEqual(self._related("sign-in failure", similarity="9"), [self.oauth.pk])

    def test_slider_is_folded_at_the_default_and_open_off_it(self):
        slider = self._search("sign-in failure").context["related_slider"]
        self.assertEqual((slider["value"], slider["count"], slider["open"]), (0.45, 1, False))
        slider = self._search("sign-in failure", similarity="0.40").context["related_slider"]
        self.assertEqual((slider["value"], slider["count"], slider["open"]), (0.40, 2, True))

    def test_nothing_related_suggests_a_looser_cutoff(self):
        # "charged" is a billing word no note contains; it scores the mixed
        # note ~0.41 and the others ~0.
        response = self._search("charged", similarity="0.50")
        slider = response.context["related_slider"]
        self.assertEqual(slider["count"], 0)
        self.assertEqual(slider["loosen_to"], 0.40)
        self.assertContains(response, "Loosen to 0.40")

    def test_no_slider_without_semantic_search(self):
        self.user.profile.ai_features_enabled = False
        self.user.profile.save()
        self.assertIsNone(self._search("sign-in failure").context["related_slider"])


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

    def test_reports_apply_the_cutoff(self):
        strict = self._get("api_v2:report-totals").json()
        loose = self._get("api_v2:report-totals", similarity="0.40").json()
        self.assertGreater(loose["session_count"], strict["session_count"])

    def test_projects_echo_the_cutoff(self):
        response = self._get("api_v2:projects", similarity="0.38")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Autumn-Related-Similarity"], "0.38")


class ChartsAndProfileTests(SemanticSearchTestCase):
    def test_charts_show_the_cutoff_in_use(self):
        response = self.client.get(
            reverse("charts"), {"search": "sign-in", "related": "on", "similarity": "0.38"}
        )
        self.assertIn({"label": "Closeness", "value": "0.38"}, response.context["active_filters"])
        self.assertEqual(response.context["related_slider"]["value"], 0.38)
        default = self.client.get(reverse("charts"), {"search": "sign-in", "related": "on"})
        self.assertIn({"label": "Closeness", "value": "0.45"}, default.context["active_filters"])

    def _form(self, data):
        form = ProfileUpdateForm(data=data, instance=self.user.profile)
        self.assertTrue(form.is_valid(), form.errors)
        return form.cleaned_data["related_similarity"]

    def test_profile_form_stores_a_default(self):
        self.assertEqual(self._form({"related_similarity": "0.38"}), 0.38)
        # The server's default is stored as "follow the server".
        self.assertIsNone(self._form({"related_similarity": "0.45"}))

    def test_profile_form_keeps_the_value_when_the_slider_is_not_on_the_page(self):
        self.user.profile.related_similarity = 0.38
        self.user.profile.save()
        self.assertEqual(self._form({}), 0.38)

    def test_profile_form_rejects_out_of_range(self):
        form = ProfileUpdateForm(data={"related_similarity": "0.9"}, instance=self.user.profile)
        self.assertFalse(form.is_valid())
        self.assertIn("related_similarity", form.errors)


class ProjectsRelatedPagingTests(SemanticSearchTestCase):
    def setUp(self):
        super().setUp()
        self.auth_projects = [
            Projects.objects.create(user=self.user, name=f"Auth service {n}", context=self.work)
            for n in range(6)
        ]
        self._sync()

    def _page(self, **params):
        return self.client.get(reverse("projects"), {"search": "sign-in failure", **params})

    def test_every_related_project_is_paged(self):
        first = self._page()
        page = first.context["related_page"]
        # Identity matches by keyword (its "sign-in failure" note), so it is
        # a direct match, not a related one.
        self.assertEqual(page.paginator.count, 6)
        self.assertEqual(len(first.context["related_projects"]), 5)
        self.assertContains(first, 'aria-label="Related pages"')
        second = self._page(related_page=2)
        self.assertEqual(len(second.context["related_projects"]), 1)
        shown = {p.pk for p in first.context["related_projects"] + second.context["related_projects"]}
        self.assertEqual(shown, {p.pk for p in self.auth_projects})

    def test_the_slider_count_matches_the_pages(self):
        response = self._page()
        self.assertEqual(
            response.context["related_slider"]["count"],
            response.context["related_page"].paginator.count,
        )
