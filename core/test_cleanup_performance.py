from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.models import Commitment, Context, Projects, Sessions, SubProjects, Tag
from core.totals import session_minute_totals_since


class ListQueryCountTests(TestCase):
    """The v2 sessions and projects lists issue the same queries for 2 rows or 8."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="query-cleanup")
        self.context = Context.objects.create(user=self.user, name="Work")
        self.tag = Tag.objects.create(user=self.user, name="focused")
        self.client.force_login(self.user)

    def _add(self, count):
        for index in range(count):
            project = Projects.objects.create(
                user=self.user, name=f"Project {len(Projects.objects.all())}", context=self.context
            )
            project.tags.add(self.tag)
            subproject = SubProjects.objects.create(
                user=self.user, parent_project=project, name="Sub"
            )
            end = timezone.now() - timedelta(minutes=index)
            session = Sessions.objects.create(
                user=self.user,
                project=project,
                start_time=end - timedelta(minutes=30),
                end_time=end,
            )
            session.subprojects.add(subproject)
        Commitment.objects.create(
            user=self.user,
            project=project,
            commitment_type="sessions",
            period="weekly",
            target=2,
        )

    def _queries(self, path):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        return len(queries)

    def test_lists_do_not_query_per_row(self):
        for path in ("/api/v2/sessions/", "/api/v2/projects/"):
            Sessions.objects.all().delete()
            Projects.objects.all().delete()
            self._add(2)
            few = self._queries(path)
            self._add(6)
            many = self._queries(path)
            self.assertEqual(few, many, path)


class DashboardSummaryPerformanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="dashboard-summary",
            email="dashboard-summary@example.com",
        )
        cls.other_user = get_user_model().objects.create_user(
            username="other-dashboard-summary",
            email="other-dashboard-summary@example.com",
        )
        cls.project = Projects.objects.create(user=cls.user, name="Summary")
        cls.other_project = Projects.objects.create(
            user=cls.other_user,
            name="Other summary",
        )

        now = timezone.now()
        cls.today_start = now - timedelta(hours=12)
        cls.week_start = now - timedelta(days=7)
        cls._session(cls.user, cls.project, now - timedelta(hours=1), 20.12341)
        cls._session(cls.user, cls.project, now - timedelta(days=2), 30.54321)
        cls._session(cls.user, cls.project, now - timedelta(days=9), 500)
        cls._session(cls.other_user, cls.other_project, now, 700)
        Sessions.objects.create(
            user=cls.user,
            project=cls.project,
            start_time=now - timedelta(minutes=90),
            end_time=None,
        )

    @staticmethod
    def _session(user, project, end, minutes):
        return Sessions.objects.create(
            user=user,
            project=project,
            start_time=end - timedelta(minutes=minutes),
            end_time=end,
        )

    def test_named_windows_share_one_query_and_keep_session_rounding(self):
        with self.assertNumQueries(1):
            totals = session_minute_totals_since(
                self.user,
                today=self.today_start,
                week=self.week_start,
            )

        self.assertAlmostEqual(totals["today"], 20.1234, places=4)
        self.assertAlmostEqual(totals["week"], 50.6666, places=4)

    def test_empty_windows_return_zero_without_loading_sessions(self):
        empty_user = get_user_model().objects.create_user(
            username="empty-dashboard-summary",
            email="empty-dashboard-summary@example.com",
        )

        with self.assertNumQueries(1):
            totals = session_minute_totals_since(
                empty_user,
                today=self.today_start,
                week=self.week_start,
            )

        self.assertEqual(totals, {"today": 0.0, "week": 0.0})
