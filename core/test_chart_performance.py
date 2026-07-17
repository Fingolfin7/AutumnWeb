from datetime import datetime, timedelta, timezone as datetime_timezone

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from core.models import Context, Projects, Sessions, SubProjects, Tag


UTC = datetime_timezone.utc


class ChartApiRegressionTests(TestCase):
    """Protect chart contracts while keeping their query counts bounded."""

    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.user = user_model.objects.create_user(
            username="chart-user",
            email="chart@example.com",
            password="test-password",
        )
        cls.other_user = user_model.objects.create_user(
            username="other-chart-user",
            email="other-chart@example.com",
            password="test-password",
        )

        cls.work = Context.objects.create(user=cls.user, name="Work")
        cls.personal = Context.objects.create(user=cls.user, name="Personal")
        cls.focus = Tag.objects.create(user=cls.user, name="Focus", color="#112233")
        cls.shared = Tag.objects.create(user=cls.user, name="Shared", color="#445566")

        cls.alpha = Projects.objects.create(
            user=cls.user,
            name="Alpha",
            context=cls.work,
            status="active",
        )
        cls.beta = Projects.objects.create(
            user=cls.user,
            name="Beta",
            context=cls.personal,
            status="paused",
        )
        cls.empty = Projects.objects.create(
            user=cls.user,
            name="Empty",
            context=cls.work,
            status="complete",
        )
        cls.alpha.tags.add(cls.focus, cls.shared)
        cls.beta.tags.add(cls.shared)

        cls.design = SubProjects.objects.create(
            user=cls.user,
            parent_project=cls.alpha,
            name="Design",
        )
        cls.build = SubProjects.objects.create(
            user=cls.user,
            parent_project=cls.alpha,
            name="Build",
        )

        cls.alpha_long = cls._session(
            cls.user,
            cls.alpha,
            datetime(2026, 1, 1, 9, tzinfo=UTC),
            60,
            note="Focus focus build code",
        )
        # One session in two subprojects must count once in project/context/tag
        # totals, but once in each of its two subproject buckets.
        cls.alpha_long.subprojects.add(cls.design, cls.build)
        cls.alpha_short = cls._session(
            cls.user,
            cls.alpha,
            datetime(2026, 1, 2, 9, tzinfo=UTC),
            30,
            note="Build review",
        )
        cls.beta_session = cls._session(
            cls.user,
            cls.beta,
            datetime(2026, 1, 2, 12, tzinfo=UTC),
            120,
            note="Meeting plan",
        )
        cls._session(
            cls.user,
            cls.alpha,
            datetime(2026, 1, 3, 9, tzinfo=UTC),
            45,
            note="active session is excluded",
            is_active=True,
        )

        other_context = Context.objects.create(user=cls.other_user, name="Private")
        other_project = Projects.objects.create(
            user=cls.other_user,
            name="Other user's project",
            context=other_context,
        )
        cls._session(
            cls.other_user,
            other_project,
            datetime(2026, 1, 1, 9, tzinfo=UTC),
            600,
            note="must never leak",
        )

    @staticmethod
    def _session(user, project, start, minutes, note="", is_active=False):
        return Sessions.objects.create(
            user=user,
            project=project,
            start_time=start,
            end_time=None if is_active else start + timedelta(minutes=minutes),
            note=note,
            is_active=is_active,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_login(self.user)

    def _get_chart(self, chart_type, **params):
        return self.client.get(
            "/api/v2/reports/charts/",
            {"chart_type": chart_type, **params},
        )

    def test_tally_endpoints_are_correct_without_m2m_fanout(self):
        project_rows = self.client.get("/api/v2/reports/charts/", {"chart_type": "pie"}).json()
        self.assertEqual(
            {row["name"]: row["total_time"] for row in project_rows},
            {"Alpha": 90.0, "Beta": 120.0},
        )

        # Alpha matches both selected tags. Its sessions still count only once.
        filtered_rows = self.client.get(
            "/api/v2/reports/charts/", {"chart_type": "pie"},
            {"tags": [self.focus.id, self.shared.id]},
        ).json()
        self.assertEqual(
            {row["name"]: row["total_time"] for row in filtered_rows},
            {"Alpha": 90.0, "Beta": 120.0},
        )

        subproject_rows = self.client.get("/api/v2/reports/charts/", {"chart_type": "pie", "project_name": "Alpha"}).json()
        self.assertEqual(
            {row["name"]: row["total_time"] for row in subproject_rows},
            {"Design": 60.0, "Build": 60.0, "no subproject": 30.0},
        )

        context_rows = self.client.get("/api/v2/reports/charts/", {"chart_type": "context"}).json()
        self.assertEqual(
            {row["name"]: row["total_time"] for row in context_rows},
            {"Work": 90.0, "Personal": 120.0},
        )

        status_rows = self.client.get("/api/v2/reports/charts/", {"chart_type": "status"}).json()
        self.assertEqual(
            {
                row["status"]: (row["count"], row["total_time"])
                for row in status_rows
            },
            {
                "active": (1, 90.0),
                "paused": (1, 120.0),
                "complete": (1, 0),
            },
        )

        tag_rows = self.client.get("/api/v2/reports/charts/", {"chart_type": "bubble"}).json()
        self.assertEqual(
            {
                row["name"]: (
                    row["total_time"],
                    row["project_count"],
                    row["color"],
                )
                for row in tag_rows
            },
            {
                "Focus": (90.0, 1, "#112233"),
                "Shared": (210.0, 2, "#445566"),
            },
        )

    def test_scatter_shape_and_subproject_series(self):
        response = self._get_chart("scatter")
        self.assertEqual(response.status_code, 200)
        rows = response.json()
        self.assertEqual(len(rows), 3)
        self.assertEqual(
            {(row["series"], row["y"]) for row in rows},
            {("Alpha", 1.0), ("Alpha", 0.5), ("Beta", 2.0)},
        )
        self.assertTrue(all(set(row) == {"x", "y", "series"} for row in rows))

        rows = self._get_chart("scatter", project_name="Alpha").json()
        self.assertEqual(
            {(row["series"], row["y"]) for row in rows},
            {("Design", 1.0), ("Build", 1.0), ("no subproject", 0.5)},
        )

    def test_daily_series_shapes(self):
        expected = {
            ("2026-01-01", "Alpha", 1.0),
            ("2026-01-02", "Alpha", 0.5),
            ("2026-01-02", "Beta", 2.0),
        }
        for chart_type in ("line", "stacked_area"):
            with self.subTest(chart_type=chart_type):
                response = self._get_chart(chart_type)
                self.assertEqual(response.status_code, 200)
                rows = response.json()
                self.assertEqual(
                    {
                        (row["date"], row["series"], row["hours"])
                        for row in rows
                    },
                    expected,
                )
                self.assertTrue(
                    all(set(row) == {"date", "series", "hours"} for row in rows)
                )

    def test_daily_total_shapes(self):
        expected = [
            {"date": "2026-01-01", "hours": 1.0},
            {"date": "2026-01-02", "hours": 2.5},
        ]
        for chart_type in ("calendar", "cumulative"):
            with self.subTest(chart_type=chart_type):
                response = self._get_chart(chart_type)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), expected)

    def test_heatmap_histogram_and_wordcloud_shapes(self):
        heatmap = self._get_chart("heatmap")
        self.assertEqual(heatmap.status_code, 200)
        self.assertEqual(len(heatmap.json()), 3)
        self.assertTrue(
            all(set(row) == {"start_time", "end_time"} for row in heatmap.json())
        )

        histogram = self._get_chart("histogram")
        self.assertEqual(histogram.status_code, 200)
        self.assertEqual(
            histogram.json(),
            [
                {"label": "0-15m", "count": 0},
                {"label": "15-30m", "count": 0},
                {"label": "30-60m", "count": 1},
                {"label": "1-2h", "count": 1},
                {"label": "2-4h", "count": 1},
                {"label": "4-8h", "count": 0},
                {"label": "8h+", "count": 0},
            ],
        )

        wordcloud = self._get_chart("wordcloud")
        self.assertEqual(wordcloud.status_code, 200)
        weights = {row["text"]: row["weight"] for row in wordcloud.json()}
        self.assertEqual(weights["focus"], 2)
        self.assertEqual(weights["build"], 2)
        self.assertNotIn("leak", weights)
        self.assertTrue(
            all(set(row) == {"text", "weight"} for row in wordcloud.json())
        )

    def test_chart_filters_match_ui_parameter_semantics(self):
        cases = (
            ({"start_date": "2026-01-02"}, {"Alpha", "Beta"}),
            ({"end_date": "2026-01-01"}, {"Alpha"}),
            ({"project_name": "Alpha"}, {"Design", "Build", "no subproject"}),
            ({"context": self.personal.id}, {"Beta"}),
            ({"tags": [self.focus.id]}, {"Alpha"}),
            ({"exclude_projects": [self.alpha.id]}, {"Beta"}),
        )
        for params, expected_series in cases:
            with self.subTest(params=params):
                response = self._get_chart("scatter", **params)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    {row["series"] for row in response.json()},
                    expected_series,
                )

    def test_invalid_chart_type_returns_400(self):
        response = self._get_chart("not-a-chart")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "error": {
                    "code": "validation_error",
                    "message": "Invalid input.",
                    "details": {
                        "chart_type": ["Unsupported chart_type."]
                    },
                }
            },
        )

    def test_empty_histogram_preserves_empty_chart_state(self):
        Sessions.objects.filter(user=self.user).delete()
        self.assertEqual(self._get_chart("histogram").json(), [])

    def test_list_sessions_queries_remain_constant_as_session_count_grows(self):
        endpoint = "/api/v2/sessions/"
        self.client.get(endpoint)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(endpoint)
        self.assertEqual(response.status_code, 200)
        baseline = len(queries)

        Sessions.objects.bulk_create(
            [
                Sessions(
                    user=self.user,
                    project=self.alpha,
                    start_time=datetime(2026, 4, 1, 9, tzinfo=UTC)
                    + timedelta(days=index),
                    end_time=datetime(2026, 4, 1, 9, tzinfo=UTC)
                    + timedelta(days=index, minutes=10),
                    is_active=False,
                )
                for index in range(25)
            ]
        )

        with CaptureQueriesContext(connection) as queries:
            self.client.get(endpoint)
        grown = len(queries)
        self.assertLessEqual(grown, 10)
        self.assertLessEqual(grown, baseline + 1)

    def test_chart_queries_remain_constant_as_session_count_grows(self):
        # Warm authentication/session code so one-time lookups do not skew either
        # side of the comparison.
        chart_types = (
            "scatter",
            "line",
            "calendar",
            "heatmap",
            "stacked_area",
            "cumulative",
            "histogram",
            "wordcloud",
        )
        baseline_counts = {}
        for chart_type in chart_types:
            self._get_chart(chart_type)
            with CaptureQueriesContext(connection) as queries:
                self._get_chart(chart_type)
            baseline_counts[chart_type] = len(queries)

        Sessions.objects.bulk_create(
            [
                Sessions(
                    user=self.user,
                    project=self.alpha,
                    start_time=datetime(2026, 2, 1, 9, tzinfo=UTC)
                    + timedelta(days=index),
                    end_time=datetime(2026, 2, 1, 9, tzinfo=UTC)
                    + timedelta(days=index, minutes=10),
                    note=f"bulk note {index}",
                    is_active=False,
                )
                for index in range(25)
            ]
        )

        for chart_type in chart_types:
            with self.subTest(chart_type=chart_type):
                with CaptureQueriesContext(connection) as queries:
                    self._get_chart(chart_type)
                grown = len(queries)
                self.assertLessEqual(grown, 10)
                self.assertLessEqual(grown, baseline_counts[chart_type] + 1)

    def test_tally_queries_remain_constant_as_session_count_grows(self):
        endpoints = (
            "/api/v2/reports/charts/?chart_type=pie",
            "/api/v2/reports/charts/?chart_type=context",
            "/api/v2/reports/charts/?chart_type=status",
            "/api/v2/reports/charts/?chart_type=bubble",
        )
        baseline_counts = {}
        for endpoint in endpoints:
            self.client.get(endpoint)
            with CaptureQueriesContext(connection) as queries:
                self.client.get(endpoint)
            baseline_counts[endpoint] = len(queries)

        Sessions.objects.bulk_create(
            [
                Sessions(
                    user=self.user,
                    project=self.alpha,
                    start_time=datetime(2026, 3, 1, 9, tzinfo=UTC)
                    + timedelta(days=index),
                    end_time=datetime(2026, 3, 1, 9, tzinfo=UTC)
                    + timedelta(days=index, minutes=10),
                    is_active=False,
                )
                for index in range(25)
            ]
        )

        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                with CaptureQueriesContext(connection) as queries:
                    self.client.get(endpoint)
                grown = len(queries)
                self.assertLessEqual(grown, 10)
                self.assertLessEqual(grown, baseline_counts[endpoint] + 1)
