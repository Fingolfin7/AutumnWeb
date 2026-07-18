from datetime import datetime, timedelta, timezone as datetime_timezone

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import Context, Projects, Sessions, SessionSubproject, SubProjects, Tag


UTC = datetime_timezone.utc


class V2ReportsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="report-user",
            email="report-user@example.com",
            password="secret",
        )
        self.work = Context.objects.create(user=self.user, name="Work")
        self.focus = Tag.objects.create(user=self.user, name="Focus")
        self.shared = Tag.objects.create(user=self.user, name="Shared")
        self.alpha = Projects.objects.create(
            user=self.user, name="Alpha", context=self.work, status="active"
        )
        self.alpha.tags.add(self.focus, self.shared)
        self.beta = Projects.objects.create(user=self.user, name="Beta", status="paused")
        self.beta.tags.add(self.shared)
        Projects.objects.filter(pk=self.beta.pk).update(context=None)

        self.alpha_a = self._subproject(self.alpha, "Alpha A")
        self.alpha_b = self._subproject(self.alpha, "Alpha B")
        self.beta_a = self._subproject(self.beta, "Beta A")
        partitioned = self._session(
            self.alpha, 1, 10, 60, note="design autumn design"
        )
        self._link(partitioned, self.alpha_a, 3000)
        self._link(partitioned, self.alpha_b, 7000)
        self._session(
            self.alpha, 1, 12, 30, note="review charts"
        )
        beta_session = self._session(self.beta, 2, 10, 45, note="planning")
        self._link(beta_session, self.beta_a, 10000)

        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _subproject(self, project, name):
        return SubProjects.objects.create(
            user=self.user, parent_project=project, name=name
        )

    def _session(self, project, day, hour, minutes, *, note=""):
        start = datetime(2026, 1, day, hour, tzinfo=UTC)
        return Sessions.objects.create(
            user=self.user,
            project=project,
            start_time=start,
            end_time=start + timedelta(minutes=minutes),
            note=note,
            is_active=False,
        )

    @staticmethod
    def _link(session, subproject, allocation_bp):
        return SessionSubproject.objects.create(
            session=session, subproject=subproject, allocation_bp=allocation_bp
        )

    def _tally(self, tally_kind):
        response = self.client.get(
            reverse("api_v2:report-tallies"), {"by": tally_kind}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["by"], tally_kind)
        return response.json()["entries"]

    def test_totals_use_full_session_duration(self):
        response = self.client.get(reverse("api_v2:report-totals"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"total_minutes": 135.0, "session_count": 3}
        )

    def test_project_tally(self):
        self.assertEqual(
            self._tally("project"),
            [
                {"id": self.alpha.id, "name": "Alpha", "total_minutes": 90.0, "session_count": 2},
                {"id": self.beta.id, "name": "Beta", "total_minutes": 45.0, "session_count": 1},
            ],
        )

    def test_context_tally_includes_general_null_bucket(self):
        self.assertEqual(
            self._tally("context"),
            [
                {"id": self.work.id, "name": "Work", "total_minutes": 90.0, "session_count": 2},
                {"id": None, "name": "General", "total_minutes": 45.0, "session_count": 1},
            ],
        )

    def test_status_tally(self):
        self.assertEqual(
            self._tally("status"),
            [
                {"id": None, "name": "active", "total_minutes": 90.0, "session_count": 2},
                {"id": None, "name": "paused", "total_minutes": 45.0, "session_count": 1},
            ],
        )

    def test_tag_tally_uses_full_duration_per_tag(self):
        self.assertEqual(
            self._tally("tag"),
            [
                {"id": self.shared.id, "name": "Shared", "total_minutes": 135.0, "session_count": 3},
                {"id": self.focus.id, "name": "Focus", "total_minutes": 90.0, "session_count": 2},
            ],
        )

    def test_subproject_tally_has_weighted_links_and_project_residual(self):
        self.assertEqual(
            self._tally("subproject"),
            [
                {"kind": "subproject", "id": self.beta_a.id, "name": "Beta A", "project_id": self.beta.id, "total_minutes": 45.0},
                {"kind": "subproject", "id": self.alpha_b.id, "name": "Alpha B", "project_id": self.alpha.id, "total_minutes": 42.0},
                {"kind": "residual", "project_id": self.alpha.id, "id": None, "name": None, "total_minutes": 30.0},
                {"kind": "subproject", "id": self.alpha_a.id, "name": "Alpha A", "project_id": self.alpha.id, "total_minutes": 18.0},
            ],
        )

    def test_partitioned_hierarchy_is_additive_and_has_residual_shape(self):
        response = self.client.get(reverse("api_v2:report-hierarchy"))
        self.assertEqual(response.status_code, 200)
        alpha = next(
            item for item in response.json()["projects"] if item["id"] == self.alpha.id
        )
        self.assertEqual(alpha["total_minutes"], 90.0)
        self.assertEqual(
            round(sum(child["total_minutes"] for child in alpha["children"]), 2),
            alpha["total_minutes"],
        )
        residual = next(
            child for child in alpha["children"] if child["kind"] == "residual"
        )
        self.assertEqual(
            residual,
            {"kind": "residual", "project_id": self.alpha.id, "id": None, "name": None, "total_minutes": 30.0},
        )

    def test_chart_types_preserve_former_payload_keys(self):
        expected_keys = {
            "scatter": {"x", "y", "series"},
            "line": {"date", "series", "hours"},
            "stacked_area": {"date", "series", "hours"},
            "calendar": {"date", "hours"},
            "cumulative": {"date", "hours"},
            "heatmap": {"start_time", "end_time"},
            "histogram": {"label", "count"},
            "wordcloud": {"text", "weight"},
        }
        for chart_type, keys in expected_keys.items():
            with self.subTest(chart_type=chart_type):
                response = self.client.get(
                    reverse("api_v2:report-charts"), {"chart_type": chart_type}
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json())
                self.assertEqual(set(response.json()[0]), keys)

    def test_chart_date_filter_uses_yyyy_mm_dd(self):
        response = self.client.get(
            reverse("api_v2:report-charts"),
            {"chart_type": "calendar", "start_date": "2026-01-02", "end_date": "2026-01-02"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{"date": "2026-01-02", "hours": 0.75}])

    def test_v1_chart_data_route_is_removed(self):
        response = self.client.get("/api/chart_data/", {"chart_type": "line"})
        self.assertEqual(response.status_code, 404)

    def test_web_charts_template_references_only_v2_chart_url(self):
        web_client = Client()
        web_client.force_login(self.user)
        response = web_client.get(reverse("charts"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("api_v2:report-charts"))
        self.assertNotContains(response, "/api/chart_data/")
        self.assertNotContains(response, "api_chart_data")
