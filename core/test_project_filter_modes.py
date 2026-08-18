"""Tests for the two-mode project filter.

The picker submits its ticks as either ``include_projects`` or
``exclude_projects``. Two fields rather than one field plus a mode flag, so an
existing ``?exclude_projects=`` link keeps its old meaning — that backward
compatibility is what half of these pin down. The other half pin the order the
two lists compose in: include narrows the field first, then exclude subtracts.
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

    def _session_projects(self, params):
        response = self.client.get(reverse("sessions"), params)
        self.assertEqual(response.status_code, 200)
        return {s.project.name for s in response.context["object_list"]}

    def _listed_projects(self, params):
        response = self.client.get(reverse("projects"), params)
        self.assertEqual(response.status_code, 200)
        return {p.name for p in response.context["object_list"]}


class SessionListModeTests(ProjectFilterModeTestCase):
    def test_include_keeps_only_the_named_projects(self):
        self.assertEqual(
            self._session_projects({"include_projects": [str(self.atlas.id)]}),
            {"Atlas API"},
        )

    def test_exclude_alone_still_means_what_it_always_meant(self):
        """Old bookmarks and CLI calls must not change behaviour."""
        self.assertEqual(
            self._session_projects({"exclude_projects": [str(self.atlas.id)]}),
            {"Autumn", "Mirror"},
        )

    def test_include_narrows_first_then_exclude_subtracts(self):
        both = {
            "include_projects": [str(self.atlas.id), str(self.autumn.id)],
            "exclude_projects": [str(self.autumn.id)],
        }
        self.assertEqual(self._session_projects(both), {"Atlas API"})

    def test_exclude_cannot_widen_the_included_set(self):
        """Excluding something outside the include list leaves it untouched."""
        both = {
            "include_projects": [str(self.atlas.id)],
            "exclude_projects": [str(self.mirror.id)],
        }
        self.assertEqual(self._session_projects(both), {"Atlas API"})

    def test_junk_include_id_does_not_raise_or_filter(self):
        """Query strings are user input; a non-numeric id must not 500."""
        self.assertEqual(
            self._session_projects({"include_projects": ["not-a-number"]}),
            {"Atlas API", "Autumn", "Mirror"},
        )


class ProjectsListModeTests(ProjectFilterModeTestCase):
    def test_include_keeps_only_the_named_projects(self):
        self.assertEqual(
            self._listed_projects({"include_projects": [str(self.autumn.id)]}),
            {"Autumn"},
        )

    def test_include_narrows_first_then_exclude_subtracts(self):
        both = {
            "include_projects": [str(self.atlas.id), str(self.autumn.id)],
            "exclude_projects": [str(self.atlas.id)],
        }
        self.assertEqual(self._listed_projects(both), {"Autumn"})


class FilterSummaryTests(ProjectFilterModeTestCase):
    def test_included_projects_are_echoed_as_their_own_pill(self):
        response = self.client.get(
            reverse("sessions"), {"include_projects": [str(self.atlas.id)]}
        )
        self.assertIn(
            {"label": "Only", "value": "Atlas API"}, response.context["active_filters"]
        )

    def test_both_pills_can_be_shown_at_once(self):
        response = self.client.get(
            reverse("sessions"),
            {
                "include_projects": [str(self.atlas.id), str(self.autumn.id)],
                "exclude_projects": [str(self.autumn.id)],
            },
        )
        labels = {item["label"]: item["value"] for item in response.context["active_filters"]}
        self.assertEqual(labels["Only"], "Atlas API, Autumn")
        self.assertEqual(labels["Excluding"], "Autumn")

    def test_another_users_project_resolves_to_nothing(self):
        other = User.objects.create_user(
            username="curufin", email="curufin@example.com", password="pw"
        )
        theirs = Projects.objects.create(user=other, name="Forge")

        response = self.client.get(
            reverse("sessions"), {"include_projects": [str(theirs.id)]}
        )

        self.assertEqual(response.context["active_filters"], [])


class PickerModeRenderingTests(ProjectFilterModeTestCase):
    """Which mode the sheet comes back in follows the query, not a cookie."""

    def test_default_is_the_exclude_mode(self):
        html = self.client.get(reverse("sessions")).content.decode()
        self.assertRegex(html, r'data-picker-mode="exclude"[^>]*aria-pressed="true"')
        self.assertIn('name="exclude_projects"', html)
        self.assertNotIn('name="include_projects"', html.replace('data-picker-name="include_projects"', ""))

    def test_an_include_query_comes_back_in_include_mode(self):
        html = self.client.get(
            reverse("sessions"), {"include_projects": [str(self.atlas.id)]}
        ).content.decode()

        # The include half of the toggle is the pressed one...
        self.assertRegex(
            html,
            r'data-picker-mode="include"[^>]*aria-pressed="true"',
        )
        self.assertRegex(
            html,
            r'data-picker-mode="exclude"[^>]*aria-pressed="false"',
        )
        self.assertIn('name="include_projects"', html)
        self.assertNotIn(
            'name="exclude_projects"',
            html.replace('data-picker-name="exclude_projects"', ""),
        )


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
