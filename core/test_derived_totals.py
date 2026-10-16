from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.models import Projects, Sessions, SubProjects
from core.totals import (
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
