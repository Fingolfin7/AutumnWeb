"""Search means the same thing on every surface that browses tracked work.

These ran against the old Projects, Sessions and Charts pages; the React pages
read the same rules through /api/v2/projects/, /api/v2/sessions/ and
/api/v2/reports/charts/ (core.search is shared)."""

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
        self.alpha = Projects.objects.create(
            user=self.user, name="Atlas", description="Identity management and SSO"
        )
        self.beta = Projects.objects.create(user=self.user, name="Garden")
        foreign = Projects.objects.create(
            user=other_user, name="Secret Atlas", description="Private identity management"
        )

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
            ("  IDENTITY management  ", {self.alpha.pk}),
            ("private", set()),
        )
        for term, expected in cases:
            with self.subTest(term=term):
                response = self.client.get(reverse("api_v2:projects"), {"search": term})
                self.assertEqual(response.status_code, 200, response.content)
                ids = [row["id"] for row in response.json()["projects"]]
                self.assertEqual(set(ids), expected)
                self.assertEqual(len(ids), len(expected))  # each project once
                self.assertEqual(response.json()["total"], len(expected))

    def test_sessions_match_only_assigned_subprojects_or_own_notes(self):
        cases = (
            ("atlas", {self.alpha_session.pk}),
            ("invoices", {self.alpha_session.pk, self.beta_session.pk}),
            ("payments", {self.alpha_session.pk}),
            ("unused ledger", set()),
            ("private", set()),
            ("identity management", set()),
        )
        for term, expected in cases:
            with self.subTest(term=term):
                response = self.client.get(reverse("api_v2:sessions"), {"search": term})
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual({row["id"] for row in response.json()["sessions"]}, expected)
                self.assertEqual(response.json()["total"], len(expected))


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
