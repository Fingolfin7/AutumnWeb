from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.test import RequestFactory, TestCase
from django.utils import timezone

from core.models import Commitment, Context, Projects, Sessions, SubProjects, Tag
from core.totals import session_minute_totals_since
from core.views.contexts_tags import _sidebar_project_stats
from core.views.projects import ProjectsListView
from core.views.sessions import SessionsListView


class RelationshipLoadingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="query-cleanup")
        cls.context = Context.objects.create(user=cls.user, name="Work")
        cls.tag = Tag.objects.create(user=cls.user, name="focused")
        cls.projects = []
        for index in range(4):
            project = Projects.objects.create(
                user=cls.user,
                name=f"Project {index}",
                context=cls.context,
            )
            project.tags.add(cls.tag)
            cls.projects.append(project)

            subproject = SubProjects.objects.create(
                user=cls.user,
                parent_project=project,
                name=f"Subproject {index}",
            )
            end = timezone.now() - timedelta(minutes=index)
            session = Sessions.objects.create(
                user=cls.user,
                project=project,
                start_time=end - timedelta(minutes=30),
                end_time=end,
            )
            session.subprojects.add(subproject)

        Commitment.objects.create(
            user=cls.user,
            project=cls.projects[0],
            commitment_type="sessions",
            period="weekly",
            target=2,
        )

    def _request(self, path):
        request = RequestFactory().get(path)
        request.user = self.user
        request.session = {}
        return request

    def test_sessions_load_project_and_subprojects_in_two_queries(self):
        view = SessionsListView()
        view.request = self._request("/sessions/")

        with self.assertNumQueries(2):
            sessions = list(view.get_queryset())
            for session in sessions:
                session.project.name
                list(session.subprojects.all())
                list(session.subprojects.all())

        self.assertEqual(len(sessions), 4)

    def test_projects_load_context_commitment_and_tags_in_two_queries(self):
        view = ProjectsListView()
        view.request = self._request("/projects/")

        with self.assertNumQueries(2):
            projects = list(view.get_queryset())
            for project in projects:
                project.context.name
                list(project.tags.all())
                try:
                    project.commitment.active
                except ObjectDoesNotExist:
                    pass

        self.assertEqual(len(projects), 4)


class SidebarProjectStatsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="sidebar-stats")
        context = Context.objects.create(user=self.user, name="Work")
        self.active = Projects.objects.create(
            user=self.user,
            name="Active",
            context=context,
        )
        self.paused = Projects.objects.create(
            user=self.user,
            name="Paused",
            context=context,
            status="paused",
        )
        end = timezone.now()
        Sessions.objects.create(
            user=self.user,
            project=self.active,
            start_time=end - timedelta(minutes=30),
            end_time=end,
        )

    def test_sidebar_stats_use_three_queries_and_keep_all_statuses(self):
        projects = Projects.objects.filter(user=self.user)

        with self.assertNumQueries(3):
            stats = _sidebar_project_stats(self.user, projects)

        self.assertEqual(stats["sidebar_total_projects"], 2)
        self.assertEqual(stats["sidebar_total_time"], 30)
        self.assertEqual(stats["sidebar_average_session_duration"], 30)
        self.assertEqual(
            stats["sidebar_status_counts"],
            {"active": 1, "paused": 1, "complete": 0, "archived": 0},
        )


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
