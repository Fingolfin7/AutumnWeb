"""Tests for the two-mode project filter.

The Sessions page's picker (now React) sends its ticks to /api/v2/sessions/ as
``project_ids`` (include) or ``exclude_project_ids``. They are separate fields
rather than one field plus a mode flag, so an exclude-only request keeps its
old meaning (old bookmarks and CLI calls must not change behaviour). The other
half of these pin the order the two lists compose in: include narrows the
field first, then exclude subtracts. The Projects page applies "include" in the
browser (frontend/src/features/projects/logic.test.ts); the API side of that
page is exclude_project_ids. The export form still posts the old
``include_projects`` / ``exclude_projects`` names.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Context, Projects, Sessions


class ProjectFilterModeTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="finrod", password="pw")
        self.context = Context.objects.create(user=self.user, name="Work")
        self.atlas = Projects.objects.create(
            user=self.user, name="Atlas API", context=self.context
        )
        self.autumn = Projects.objects.create(
            user=self.user, name="Autumn", context=self.context
        )
        self.mirror = Projects.objects.create(
            user=self.user, name="Mirror", context=self.context
        )
        for project in (self.atlas, self.autumn, self.mirror):
            self._session(project)
        self.client.login(username="finrod", password="pw")

    def _session(self, project, minutes_ago=30):
        end = timezone.now() - timedelta(minutes=minutes_ago)
        return Sessions.objects.create(
            user=self.user,
            project=project,
            start_time=end - timedelta(minutes=30),
            end_time=end,
        )

    def _api(self, name, params, status=200):
        response = self.client.get(reverse(name), params)
        self.assertEqual(response.status_code, status, response.content)
        return response.json()

    def _session_projects(self, params):
        rows = self._api("api_v2:sessions", params)["sessions"]
        return {row["project"]["name"] for row in rows}

    def _listed_projects(self, params):
        return {row["name"] for row in self._api("api_v2:projects", params)["projects"]}


class SessionListModeTests(ProjectFilterModeTestCase):
    def test_include_keeps_only_the_named_projects(self):
        self.assertEqual(
            self._session_projects({"project_ids": str(self.atlas.id)}), {"Atlas API"}
        )

    def test_exclude_alone_still_means_what_it_always_meant(self):
        self.assertEqual(
            self._session_projects({"exclude_project_ids": str(self.atlas.id)}),
            {"Autumn", "Mirror"},
        )

    def test_include_narrows_first_then_exclude_subtracts(self):
        both = {
            "project_ids": f"{self.atlas.id},{self.autumn.id}",
            "exclude_project_ids": str(self.autumn.id),
        }
        self.assertEqual(self._session_projects(both), {"Atlas API"})

    def test_exclude_cannot_widen_the_included_set(self):
        """Excluding something outside the include list leaves it untouched."""
        both = {
            "project_ids": str(self.atlas.id),
            "exclude_project_ids": str(self.mirror.id),
        }
        self.assertEqual(self._session_projects(both), {"Atlas API"})

    def test_junk_ids_are_a_validation_error_not_a_500(self):
        """Query strings are user input. (The old page ignored junk ids; an API
        client is told, with a field-level error.)"""
        body = self._api("api_v2:sessions", {"project_ids": "not-a-number"}, status=400)
        self.assertEqual(body["error"]["code"], "validation_error")
        self.assertIn("project_ids", body["error"]["details"])

    def test_another_users_project_is_rejected_not_silently_empty(self):
        other = User.objects.create_user(
            username="curufin", email="curufin@example.com", password="pw"
        )
        theirs = Projects.objects.create(user=other, name="Forge")
        for field in ("project_ids", "exclude_project_ids"):
            with self.subTest(field=field):
                body = self._api("api_v2:sessions", {field: str(theirs.id)}, status=400)
                self.assertIn(field, body["error"]["details"])


class ProjectsListModeTests(ProjectFilterModeTestCase):
    def test_exclude_subtracts_from_the_list(self):
        self.assertEqual(
            self._listed_projects({"exclude_project_ids": str(self.atlas.id)}),
            {"Autumn", "Mirror"},
        )

    def test_another_users_project_is_rejected(self):
        other = User.objects.create_user(
            username="curufin", email="curufin@example.com", password="pw"
        )
        theirs = Projects.objects.create(user=other, name="Forge")
        body = self._api(
            "api_v2:projects", {"exclude_project_ids": str(theirs.id)}, status=400
        )
        self.assertIn("exclude_project_ids", body["error"]["details"])


class ExportModeTests(ProjectFilterModeTestCase):
    def _exported_names(self, payload):
        response = self.client.post(reverse("export"), payload)
        self.assertEqual(response.status_code, 200)
        return {project["name"] for project in response.json()["projects"]}

    def test_include_keeps_only_the_named_projects(self):
        self.assertEqual(
            self._exported_names({"include_projects": [str(self.atlas.id)]}),
            {"Atlas API"},
        )

    def test_include_narrows_first_then_exclude_subtracts(self):
        names = self._exported_names(
            {
                "include_projects": [str(self.atlas.id), str(self.autumn.id)],
                "exclude_projects": [str(self.autumn.id)],
            }
        )
        self.assertEqual(names, {"Atlas API"})
