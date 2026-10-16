from datetime import datetime, timedelta, timezone as datetime_timezone
from django.contrib.auth import get_user_model
from django.test import TestCase
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


    def test_wordcloud_cleans_markdown(self):
        self._session(
            self.user,
            self.alpha,
            datetime(2026, 1, 4, 9, tzinfo=UTC),
            15,
            note=(
                "# Focus **build** [review](https://example.invalid) "
                "`inline secret` ```hidden code```"
            ),
        )

        weights = {
            row["text"]: row["weight"]
            for row in self._get_chart("wordcloud").json()
        }

        self.assertGreaterEqual(weights["focus"], 3)
        self.assertGreaterEqual(weights["build"], 3)
        self.assertEqual(weights["review"], 2)
        self.assertNotIn("secret", weights)
        self.assertNotIn("hidden", weights)
        self.assertNotIn("invalid", weights)

    def test_heatmap_respects_profile_timezone_across_spring_forward(self):
        Sessions.objects.filter(user=self.user).delete()
        self.user.profile.timezone = "America/New_York"
        self.user.profile.save(update_fields=["timezone"])
        self._session(
            self.user,
            self.alpha,
            datetime(2026, 3, 8, 6, 30, tzinfo=UTC),
            60,
        )

        rows = self._get_chart("heatmap", aggregate="true").json()

        cells = {
            (row["weekday"], row["hour"]): row["average_hours"]
            for row in rows
        }
        self.assertEqual(cells, {(0, 1): 0.5, (0, 3): 0.5})

    def test_heatmap_accounts_for_the_repeated_fall_back_hour(self):
        Sessions.objects.filter(user=self.user).delete()
        self.user.profile.timezone = "America/New_York"
        self.user.profile.save(update_fields=["timezone"])
        self._session(
            self.user,
            self.alpha,
            datetime(2026, 11, 1, 5, 30, tzinfo=UTC),
            120,
        )

        rows = self._get_chart("heatmap", aggregate="true").json()

        cells = {
            (row["weekday"], row["hour"]): row["average_hours"]
            for row in rows
        }
        self.assertEqual(cells, {(0, 1): 0.75, (0, 2): 0.5})

    def test_chart_filters_match_ui_parameter_semantics(self):
        cases = (
            ({"start_date": "2026-01-02"}, {"Alpha", "Beta"}),
            ({"end_date": "2026-01-01"}, {"Alpha"}),
            ({"project_name": "Alpha"}, {"Design", "Build", "no subproject"}),
            ({"context": self.personal.id}, {"Beta"}),
            ({"tags": [self.focus.id]}, {"Alpha"}),
            ({"exclude_projects": [self.alpha.id]}, {"Beta"}),
            ({"include_projects": [self.beta.id]}, {"Beta"}),
            (
                {
                    "include_projects": [self.alpha.id, self.beta.id],
                    "exclude_projects": [self.beta.id],
                },
                {"Alpha"},
            ),
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
