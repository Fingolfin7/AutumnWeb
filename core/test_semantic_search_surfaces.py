"""Meaning-based search beyond the Sessions list: Projects, Charts, Insights, API.

Reuses the mocked OpenAI and fixtures of core.test_semantic_search: "sign-in
failure" keyword-matches only one Identity note, while the "Repaired OAuth
token refresh" session and OAuth-flavoured projects match it by meaning.
"""


from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from core.models import Projects, RecommendationUsage
from core.services import semantic_search
from core.test_semantic_search import FakeOpenAI, SemanticSearchTestCase


def insights_session_ids(testcase, **extra):
    """The sessions an Insights chat is built from (POST /api/v2/insights/stream/)."""
    from django.test import RequestFactory

    from llm_insights.services.context import build_post_context

    request = RequestFactory().post(
        "/api/v2/insights/stream/", {"search": "sign-in failure", "filter": "1", **extra}
    )
    request.user = testcase.user
    request.session = testcase.client.session
    return [s.pk for s in build_post_context(request, testcase.user)["sessions"]]


class ProjectsRelatedTests(SemanticSearchTestCase):
    def setUp(self):
        super().setUp()
        # Related through its own description, and through a session note.
        self.accounts = Projects.objects.create(
            user=self.user, name="Accounts", description="OAuth login provider", context=self.work
        )
        self.platform = Projects.objects.create(user=self.user, name="Platform", context=self.work)
        self._session(self.platform, "Rotated OAuth signing keys", days_ago=3)
        self._sync()

    def _related(self, term, **params):
        return self._related_projects(term, **params)

    def test_related_projects_come_from_descriptions_and_session_notes(self):
        # The keyword list is unchanged: only Identity has a note with the words.
        self.assertEqual(self._project_ids("sign-in failure", related=False), [self.identity.pk])
        self.assertEqual(self._related("sign-in failure"), {self.accounts.pk, self.platform.pk})

    def test_related_projects_obey_the_list_filters(self):
        self.assertEqual(self._related("sign-in failure", context_ids=str(self.home.pk)), set())
        self.assertEqual(self._related("sign-in failure", context_ids=str(self.work.pk)),
                         {self.accounts.pk, self.platform.pk})
        self.assertEqual(
            self._related("sign-in failure", exclude_project_ids=str(self.accounts.pk)), {self.platform.pk}
        )

    def test_other_accounts_projects_never_appear(self):
        other = self._user("semantic-projects-other", "other-key")
        foreign = Projects.objects.create(user=other, name="Foreign", description="OAuth login sign-in")
        self._sync()
        self.assertNotIn(foreign.pk, self._related("sign-in failure"))


    def test_no_key_means_no_related_projects_and_no_call(self):
        self.user.profile.set_api_key("openai", None)
        self.user.profile.save()
        FakeOpenAI.instances = []
        self.assertEqual(self._related("sign-in failure"), set())
        self.assertEqual(FakeOpenAI.instances, [])


class IncludeRelatedTests(SemanticSearchTestCase):
    """Charts and Insights count related sessions only when asked to."""

    def setUp(self):
        super().setUp()
        self._sync()

    def _pie(self, **params):
        response = self.client.get(
            reverse("api_v2:report-charts"), {"chart_type": "pie", "search": "sign-in failure", **params}
        )
        self.assertEqual(response.status_code, 200)
        return {row["name"]: row["total_time"] for row in response.json()}

    def test_charts_count_related_sessions_only_with_the_toggle(self):
        self.assertEqual(self._pie(), {"Identity": 30.0})
        self.assertEqual(self._pie(related="true"), {"Identity": 60.0})
        # Still inside the other filters: the related session is 10 days old.
        old = timezone.localtime(self.oauth.end_time).date().isoformat()
        self.assertEqual(
            self._pie(related="true", end_date=old, start_date=old), {"Identity": 30.0}
        )
        self.assertEqual(self._pie(related="true", context=str(self.home.pk)), {})


    def test_insights_session_set_includes_related_only_with_the_toggle(self):
        self.assertEqual(insights_session_ids(self), [self.failure_note.pk])
        self.assertEqual(
            insights_session_ids(self, related="on"), [self.failure_note.pk, self.oauth.pk]
        )


class FailureHandlingTests(SemanticSearchTestCase):
    """A broken key or provider costs one timeout, and the pages say so."""

    def setUp(self):
        super().setUp()
        self._sync()
        FakeOpenAI.instances = []

    def _calls(self):
        return len(FakeOpenAI.all_inputs())

    def test_failure_starts_a_cooldown_without_further_calls(self):
        FakeOpenAI.fail = True
        with self.assertLogs("core.services.semantic_search", "WARNING"):
            self._search("sign-in failure")
        self.assertEqual(self._calls(), 1)
        # Another search, even with different words, skips the provider.
        self.assertEqual(self._related("oauth outage"), [])
        self.assertEqual(self._calls(), 1)
        self.assertEqual(RecommendationUsage.objects.filter(user=self.user, success=False).count(), 1)

        FakeOpenAI.fail = False
        cache.delete(semantic_search._cooldown_key(self.user))
        self.assertEqual(self._related("sign-in failure"), [self.oauth.pk])


    def test_api_header_reports_whether_related_was_included(self):
        url = reverse("api_v2:sessions")
        params = {"search": "sign-in failure", "related": "true"}
        self.assertEqual(self.client.get(url, params)["X-Autumn-Related"], "included")
        self.assertNotIn("X-Autumn-Related", self.client.get(url, {"search": "sign-in failure"}))

        cache.clear()
        FakeOpenAI.fail = True
        with self.assertLogs("core.services.semantic_search", "WARNING"):
            response = self.client.get(url, params)
        self.assertEqual(response["X-Autumn-Related"], "unavailable")
        self.assertEqual([row["id"] for row in response.json()["sessions"]], [self.failure_note.pk])

        charts = self.client.get(reverse("api_v2:report-charts"), {"chart_type": "pie", **params})
        self.assertEqual(charts["X-Autumn-Related"], "unavailable")
        projects = self.client.get(reverse("api_v2:projects"), {"search": "sign-in", "related": "true"})
        self.assertEqual(projects["X-Autumn-Related"], "unavailable")
