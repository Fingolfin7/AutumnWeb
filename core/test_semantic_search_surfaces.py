"""Meaning-based search beyond the Sessions list: Projects, Charts, Insights, API.

Reuses the mocked OpenAI and fixtures of core.test_semantic_search: "sign-in
failure" keyword-matches only one Identity note, while the "Repaired OAuth
token refresh" session and OAuth-flavoured projects match it by meaning.
"""

import json
from pathlib import Path
from unittest import mock

import numpy
from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from core.models import Projects, RecommendationUsage, SessionEmbedding, Sessions
from core.services import semantic_search
from core.services.semantic_search import DIMENSIONS
from core.test_semantic_search import FakeOpenAI, SemanticSearchTestCase


def semantic_mcp_operations():
    path = Path(settings.BASE_DIR) / "integrations/mcp/src/operations.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _session_count(document):
    return sum(len(project["sessions"]) for project in document["projects"])


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

    def test_counted_related_matches_are_not_capped(self):
        # More than any preview/candidate limit: every match above the cutoff counts.
        extra = [self._session(self.garden, f"OAuth login check {i}", days_ago=30 + i) for i in range(60)]
        self._sync()
        ids = self._session_ids(search="sign-in failure", related="true", limit=500)
        self.assertEqual(len(ids), 2 + len(extra))
        self.assertTrue({s.pk for s in extra} <= set(ids))

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


class ReviewRegressionTests(SemanticSearchTestCase):
    """Cases from the code review: each failed before its fix."""

    def setUp(self):
        super().setUp()
        self._sync()

    def test_client_construction_failure_falls_back_to_keywords(self):
        cache.clear()
        with mock.patch.object(semantic_search, "Embedder", side_effect=ValueError("bad proxy")):
            with self.assertLogs("core.services.semantic_search", "WARNING"):
                response = self._search("sign-in failure")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["related_sessions"], [])
            cache.delete(semantic_search._cooldown_key(self.user))
            with self.assertLogs("core.services.semantic_search", "WARNING"):
                response = self.client.get(reverse("projects"), {"search": "sign-in failure"})
            self.assertEqual(response.status_code, 200)

    def test_keyword_matches_do_not_use_up_the_related_preview(self):
        # 55 keyword matches outrank the paraphrase; it must still be found.
        for i in range(55):
            self._session(self.identity, f"Sign-in failure triage {i}", days_ago=20 + i)
        self._sync()
        self.assertEqual(self._related("sign-in failure"), [self.oauth.pk])

    def test_stale_vectors_do_not_use_up_the_related_preview(self):
        stale = [self._session(self.garden, f"OAuth login fix {i}", days_ago=20 + i) for i in range(55)]
        self._sync()
        Sessions.objects.filter(pk__in=[s.pk for s in stale]).update(note="Watered the orchard")
        self.assertEqual(self._related("sign-in failure"), [self.oauth.pk])

    def test_every_related_project_is_counted_by_the_api(self):
        for i in range(60):
            Projects.objects.create(user=self.user, name=f"Login service {i}", description="OAuth")
        self._sync()
        response = self.client.get(
            reverse("api_v2:projects"), {"search": "sign-in", "related": "true", "limit": 500}
        )
        self.assertEqual(response.json()["total"], 61)  # the 60 and Identity

    def test_corrupt_vector_of_the_right_size_is_ignored(self):
        nan = numpy.full(DIMENSIONS, numpy.nan, dtype="<f4").tobytes()
        SessionEmbedding.objects.filter(session=self.plants).update(vector=nan)
        response = self.client.get(
            reverse("api_v2:sessions"), {"search": "sign-in failure", "related": "true"}
        )
        self.assertNotIn(self.plants.pk, [row["id"] for row in response.json()["sessions"]])
        ids, _, _ = semantic_search.load_vectors(self.user, Sessions.objects.filter(user=self.user))
        self.assertNotIn(self.plants.pk, ids)

    def test_charts_api_validates_related_strictly(self):
        for value in ("maybe", "1"):
            with self.subTest(value=value):
                response = self.client.get(
                    reverse("api_v2:report-charts"),
                    {"chart_type": "pie", "search": "sign-in failure", "related": value},
                )
                self.assertEqual(response.status_code, 400)

    def test_export_documents_search_and_related(self):
        operations = {op["name"]: op for op in semantic_mcp_operations()}
        properties = operations["export_data"]["inputSchema"]["properties"]
        self.assertIn("search", properties)
        self.assertIn("related", properties)

    def test_export_applies_search_and_related(self):
        url = reverse("api_v2:export")
        keyword = self.client.get(url, {"search": "sign-in failure"}).json()
        related = self.client.get(url, {"search": "sign-in failure", "related": "true"}).json()
        self.assertLess(_session_count(keyword), _session_count(related))


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

    def test_cooldown_is_per_account(self):
        other = self._user("semantic-cooldown-other", "other-key")
        self._session(Projects.objects.create(user=other, name="Auth"), "OAuth login repair", user=other)
        self._sync()
        FakeOpenAI.fail = True
        with self.assertLogs("core.services.semantic_search", "WARNING"):
            self._search("sign-in failure")
        FakeOpenAI.fail = False
        self.client.force_login(other)
        before = self._calls()
        self._search("sign-in failure")
        self.assertEqual(self._calls(), before + 1)

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

    def test_api_header_is_unavailable_without_a_key(self):
        self.user.profile.ai_features_enabled = False
        self.user.profile.save()
        response = self.client.get(
            reverse("api_v2:report-totals"), {"search": "sign-in failure", "related": "true"}
        )
        self.assertEqual(response["X-Autumn-Related"], "unavailable")
        self.assertEqual(response.json()["session_count"], 1)

    def test_insights_pill_says_when_related_is_unavailable(self):
        url = reverse("insights")
        params = {"search": "sign-in failure", "related": "on", "filter": "true"}
        response = self.client.get(url, params)
        self.assertContains(response, 'id="related-pill"')
        self.assertContains(response, "Including <b>related</b>")

        cache.clear()
        FakeOpenAI.fail = True
        with self.assertLogs("core.services.semantic_search", "WARNING"):
            response = self.client.get(url, params)
        self.assertEqual(response.context["session_count"], 1)
        self.assertContains(response, "Related <b>unavailable</b>")
        self.assertContains(response, "only keyword matches are counted")
