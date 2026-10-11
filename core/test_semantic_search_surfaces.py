"""Meaning-based search beyond the Sessions list: Projects, Charts, Insights, API.

Reuses the mocked OpenAI and fixtures of core.test_semantic_search: "sign-in
failure" keyword-matches only one Identity note, while the "Repaired OAuth
token refresh" session and OAuth-flavoured projects match it by meaning.
"""

from django.urls import reverse
from django.utils import timezone

from core.models import Projects
from core.test_semantic_search import FakeOpenAI, SemanticSearchTestCase


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

    def _projects(self, term, **params):
        return self.client.get(reverse("projects"), {"search": term, **params})

    def _related(self, term, **params):
        return {project.pk for project in self._projects(term, **params).context["related_projects"]}

    def test_related_projects_come_from_descriptions_and_session_notes(self):
        response = self._projects("sign-in failure")
        # The keyword list is unchanged: only Identity has a note with the words.
        self.assertEqual([p.pk for p in response.context["projects"]], [self.identity.pk])
        self.assertEqual(
            {p.pk for p in response.context["related_projects"]}, {self.accounts.pk, self.platform.pk}
        )
        self.assertContains(response, 'aria-label="Related projects"')

    def test_related_projects_obey_the_page_filters(self):
        self.assertEqual(self._related("sign-in failure", context=str(self.home.pk)), set())
        self.assertEqual(
            self._related("sign-in failure", exclude_projects=str(self.accounts.pk)), {self.platform.pk}
        )
        self.assertEqual(
            self._related("sign-in failure", include_projects=str(self.accounts.pk)), {self.accounts.pk}
        )

    def test_other_accounts_projects_never_appear(self):
        other = self._user("semantic-projects-other", "other-key")
        foreign = Projects.objects.create(user=other, name="Foreign", description="OAuth login sign-in")
        self._sync()
        self.assertNotIn(foreign.pk, self._related("sign-in failure"))

    def test_stale_project_vector_is_not_used(self):
        Projects.objects.filter(pk=self.accounts.pk).update(description="Garden tools")
        self.assertEqual(self._related("sign-in failure"), {self.platform.pk})

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

    def test_charts_page_shows_the_toggle_only_when_available(self):
        response = self.client.get(reverse("charts"), {"search": "sign-in failure", "related": "on"})
        self.assertContains(response, 'id="related-search"')
        self.assertContains(response, "Including")

        self.user.profile.ai_features_enabled = False
        self.user.profile.save()
        response = self.client.get(reverse("charts"), {"search": "sign-in failure", "related": "on"})
        self.assertNotContains(response, 'id="related-search"')
        self.assertNotContains(response, "Including")

    def test_charts_ignore_related_when_ai_is_off(self):
        self.user.profile.ai_features_enabled = False
        self.user.profile.save()
        FakeOpenAI.instances = []
        self.assertEqual(self._pie(related="true"), {"Identity": 30.0})
        self.assertEqual(FakeOpenAI.instances, [])

    def test_insights_session_set_includes_related_only_with_the_toggle(self):
        url = reverse("insights")
        base = {"search": "sign-in failure", "filter": "true"}
        self.assertEqual(self.client.get(url, base).context["session_count"], 1)
        response = self.client.get(url, {**base, "related": "on"})
        self.assertEqual(response.context["session_count"], 2)
        self.assertContains(response, 'id="related-search"')

    def test_sessions_page_list_stays_keyword_only(self):
        response = self._search("sign-in failure", related="on")
        self.assertEqual([s.pk for s in response.context["object_list"]], [self.failure_note.pk])
        self.assertEqual([s.pk for s in response.context["related_sessions"]], [self.oauth.pk])
        self.assertNotContains(response, "Including")


class ApiRelatedTests(SemanticSearchTestCase):
    def setUp(self):
        super().setUp()
        self.accounts = Projects.objects.create(
            user=self.user, name="Accounts", description="OAuth login provider"
        )
        self._sync()

    def _sessions(self, **params):
        return self.client.get(reverse("api_v2:sessions"), params)

    def _session_ids(self, **params):
        response = self._sessions(**params)
        self.assertEqual(response.status_code, 200, response.content)
        return [row["id"] for row in response.json()["sessions"]]

    def test_sessions_search_is_keyword_unless_related(self):
        self.assertEqual(self._session_ids(search="sign-in failure"), [self.failure_note.pk])
        self.assertEqual(
            self._session_ids(search="sign-in failure", related="true"),
            [self.failure_note.pk, self.oauth.pk],
        )
        self.assertEqual(self._sessions(search="sign-in failure", related="true").json()["total"], 2)

    def test_sessions_related_obeys_other_filters(self):
        recent = timezone.localtime(self.failure_note.end_time).date().isoformat()
        self.assertEqual(
            self._session_ids(search="sign-in failure", related="true", start_date=recent),
            [self.failure_note.pk],
        )
        self.assertEqual(
            self._session_ids(
                search="sign-in failure", related="true", exclude_project_ids=str(self.identity.pk)
            ),
            [],
        )

    def test_invalid_related_is_rejected(self):
        response = self._sessions(search="x", related="maybe")
        self.assertEqual(response.status_code, 400)

    def test_related_is_ignored_without_a_key(self):
        self.user.profile.set_api_key("openai", None)
        self.user.profile.save()
        self.assertEqual(
            self._session_ids(search="sign-in failure", related="true"), [self.failure_note.pk]
        )

    def test_report_totals_accept_search_and_related(self):
        url = reverse("api_v2:report-totals")
        self.assertEqual(self.client.get(url, {"search": "sign-in failure"}).json()["session_count"], 1)
        self.assertEqual(
            self.client.get(url, {"search": "sign-in failure", "related": "true"}).json()["session_count"],
            2,
        )

    def test_projects_list_related(self):
        url = reverse("api_v2:projects")
        names = lambda **params: {row["name"] for row in self.client.get(url, params).json()["projects"]}
        self.assertEqual(names(search="sign-in"), set())
        # Identity through its sessions, Accounts through its description.
        self.assertEqual(names(search="sign-in", related="true"), {"Identity", "Accounts"})
        self.assertEqual(
            names(search="sign-in", related="true", exclude_project_ids=str(self.accounts.pk)),
            {"Identity"},
        )

    def test_other_accounts_never_leak_through_the_api(self):
        other = self._user("semantic-api-other", "other-key")
        foreign_project = Projects.objects.create(user=other, name="Foreign", description="OAuth login")
        foreign = self._session(foreign_project, "Fixed OAuth login sign-in", user=other)
        self._sync()
        self.assertNotIn(foreign.pk, self._session_ids(search="sign-in failure", related="true"))
        projects = self.client.get(
            reverse("api_v2:projects"), {"search": "sign-in", "related": "true"}
        ).json()["projects"]
        self.assertNotIn(foreign_project.pk, [row["id"] for row in projects])
