"""Search on browse pages should mean the same thing as their visible field."""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Projects, Sessions, SubProjects


class ContentSearchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "search-user", email="search@example.com", password="pw"
        )
        other_user = User.objects.create_user(
            "other-search-user", email="other-search@example.com", password="pw"
        )
        self.alpha = Projects.objects.create(user=self.user, name="Atlas")
        self.beta = Projects.objects.create(user=self.user, name="Garden")
        foreign = Projects.objects.create(user=other_user, name="Secret Atlas")

        self.alpha_sub = SubProjects.objects.create(
            user=self.user, parent_project=self.alpha, name="Invoices"
        )
        SubProjects.objects.create(
            user=self.user, parent_project=self.beta, name="Unused Ledger"
        )
        self.alpha_session = self._session(self.alpha, "Discussed payments")
        self.alpha_session.subprojects.add(self.alpha_sub)
        self.beta_session = self._session(self.beta, "Reviewed invoices")
        self._session(foreign, "Private payment ledger", user=other_user)
        self.client.force_login(self.user)

    def _session(self, project, note, *, user=None):
        end = timezone.now() - timedelta(minutes=1)
        return Sessions.objects.create(
            user=user or self.user,
            project=project,
            start_time=end - timedelta(minutes=30),
            end_time=end,
            note=note,
        )

    def test_projects_match_name_subproject_and_note_once(self):
        cases = (
            ("atlas", {self.alpha.pk}),
            ("Invoices", {self.alpha.pk, self.beta.pk}),
            ("unused ledger", {self.beta.pk}),
            ("PAYMENTS", {self.alpha.pk}),
            ("private", set()),
        )
        for term, expected in cases:
            with self.subTest(term=term):
                response = self.client.get(reverse("projects"), {"search": term})
                self.assertEqual(
                    {project.pk for project in response.context["object_list"]},
                    expected,
                )
                self.assertEqual(len(response.context["object_list"]), len(expected))

    def test_sessions_match_only_assigned_subprojects_or_own_notes(self):
        cases = (
            ("atlas", {self.alpha_session.pk}),
            ("invoices", {self.alpha_session.pk, self.beta_session.pk}),
            ("payments", {self.alpha_session.pk}),
            ("unused ledger", set()),
            ("private", set()),
        )
        for term, expected in cases:
            with self.subTest(term=term):
                response = self.client.get(reverse("sessions"), {"search": term})
                self.assertEqual(
                    {session.pk for session in response.context["object_list"]},
                    expected,
                )
                self.assertEqual(response.context["result_count"], len(expected))

    def test_search_combines_with_existing_note_filter(self):
        response = self.client.get(
            reverse("sessions"), {"search": "invoices", "note_snippet": "reviewed"}
        )
        self.assertEqual(
            [session.pk for session in response.context["object_list"]],
            [self.beta_session.pk],
        )

    def test_visible_browse_fields_describe_scope(self):
        for page in ("projects", "sessions", "charts"):
            with self.subTest(page=page):
                response = self.client.get(reverse(page), {"search": "payments"})
                self.assertContains(response, 'name="search"')
                self.assertContains(
                    response, "Search projects, subprojects, and session notes"
                )
                self.assertIn(
                    {"label": "Search", "value": "payments"},
                    response.context["active_filters"],
                )

    def test_chart_search_uses_matching_sessions(self):
        response = self.client.get(
            reverse("api_v2:report-charts"),
            {"chart_type": "pie", "search": "payments"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {row["name"] for row in response.json()}, {"Atlas"}
        )

        response = self.client.get(
            reverse("api_v2:report-charts"),
            {"chart_type": "pie", "search": "Invoices"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {row["name"] for row in response.json()}, {"Atlas", "Garden"}
        )

    def test_charts_keep_explicit_project_breakdown_filter(self):
        response = self.client.get(reverse("charts"))
        self.assertContains(response, 'name="project_name"')
        self.assertContains(response, "Project name (show subproject breakdown)")

        response = self.client.get(
            reverse("api_v2:report-charts"),
            {"chart_type": "pie", "project_name": "Atlas"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual({row["name"] for row in response.json()}, {"Invoices"})

    def test_status_chart_counts_only_matching_projects(self):
        response = self.client.get(
            reverse("api_v2:report-charts"),
            {"chart_type": "status", "search": "payments"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sum(row["count"] for row in response.json()), 1)
