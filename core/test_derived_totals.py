from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.utils import timezone
from rest_framework.test import force_authenticate

from core.models import Projects, Sessions, SubProjects
from core.totals import (
    annotate_project_totals,
    derived_project_last_updated,
    derived_project_totals,
    derived_subproject_last_updated,
    derived_subproject_totals,
)


class DerivedTotalsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="derived", password="password"
        )
        self.client.login(username="derived", password="password")
        self.stored_fallback = timezone.make_aware(datetime(2025, 1, 2, 12))
        self.project = Projects.objects.create(
            user=self.user,
            name="Derived Project",
            last_updated=self.stored_fallback,
            total_time=999999,
        )
        self.subproject_a = SubProjects.objects.create(
            user=self.user,
            parent_project=self.project,
            name="Alpha",
            last_updated=self.stored_fallback,
            total_time=999999,
        )
        self.subproject_b = SubProjects.objects.create(
            user=self.user,
            parent_project=self.project,
            name="Beta",
            last_updated=self.stored_fallback,
            total_time=999999,
        )

    def _session(self, seconds, *, offset_minutes=0, completed=True, links=()):
        start = timezone.make_aware(datetime(2026, 2, 3, 9)) + timedelta(
            minutes=offset_minutes
        )
        session = Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=start,
            end_time=start + timedelta(seconds=seconds) if completed else None,
            is_active=not completed,
        )
        session.subprojects.add(*links)
        return session

    def test_formula_multisession_multilink_and_active_exclusion(self):
        first = self._session(
            90, links=(self.subproject_a, self.subproject_b)
        )
        second = self._session(1, offset_minutes=2, links=(self.subproject_a,))
        self._session(2, offset_minutes=3)
        self._session(
            600,
            offset_minutes=4,
            completed=False,
            links=(self.subproject_a,),
        )

        expected_project = round(first.duration, 4) + round(second.duration, 4) + round(2 / 60, 4)
        expected_a = round(first.duration, 4) + round(second.duration, 4)
        expected_b = round(first.duration, 4)

        self.assertEqual(
            derived_project_totals(self.user)[self.project.pk], expected_project
        )
        subproject_totals = derived_subproject_totals(self.user)
        self.assertEqual(subproject_totals[self.subproject_a.pk], expected_a)
        self.assertEqual(subproject_totals[self.subproject_b.pk], expected_b)



    def test_last_updated_uses_latest_completed_end_and_stored_fallback(self):
        earlier = self._session(60, offset_minutes=0, links=(self.subproject_a,))
        latest = self._session(60, offset_minutes=20, links=(self.subproject_a,))
        self._session(
            60,
            offset_minutes=40,
            completed=False,
            links=(self.subproject_a,),
        )
        empty_project = Projects.objects.create(
            user=self.user,
            name="Empty Project",
            last_updated=self.stored_fallback,
        )
        empty_subproject = SubProjects.objects.create(
            user=self.user,
            parent_project=empty_project,
            name="Empty Subproject",
            last_updated=self.stored_fallback,
        )

        project_latest = derived_project_last_updated(self.user)
        subproject_latest = derived_subproject_last_updated(self.user)
        self.assertNotEqual(earlier.end_time, latest.end_time)
        self.assertEqual(project_latest[self.project.pk], latest.end_time)
        self.assertEqual(subproject_latest[self.subproject_a.pk], latest.end_time)
        self.assertEqual(project_latest[empty_project.pk], self.stored_fallback)
        self.assertEqual(
            subproject_latest[empty_subproject.pk], self.stored_fallback
        )
        self.assertEqual(
            timezone.localdate(project_latest[self.project.pk]),
            timezone.localdate(latest.end_time),
        )


class DerivedTotalsQueryCountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="queries", password="password")
        start = timezone.make_aware(datetime(2026, 3, 1, 10))
        for index in range(3):
            project = Projects.objects.create(
                user=cls.user, name=f"Project {index}"
            )
            subproject = SubProjects.objects.create(
                user=cls.user,
                parent_project=project,
                name=f"Subproject {index}",
            )
            session = Sessions.objects.create(
                user=cls.user,
                project=project,
                start_time=start + timedelta(hours=index),
                end_time=start + timedelta(hours=index, minutes=30),
                is_active=False,
            )
            session.subprojects.add(subproject)

    def setUp(self):
        self.factory = RequestFactory()

    def _request(self, path, data=None):
        request = self.factory.get(path, data or {})
        request.session = {}
        force_authenticate(request, user=self.user)
        return request




    def test_annotation_variant_evaluates_in_one_query(self):
        with self.assertNumQueries(1):
            projects = list(
                annotate_project_totals(Projects.objects.filter(user=self.user))
            )
        self.assertEqual(len(projects), 3)
