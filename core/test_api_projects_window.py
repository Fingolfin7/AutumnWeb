"""Regression tests for date-filtered project listings (in_window import bug)."""

from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.models import Projects, Sessions


class DateFilteredProjectListingsTests(TestCase):
    """projects/grouped and list_projects crashed with ModuleNotFoundError when
    start_date/end_date were supplied (stale relative import after the api
    package split)."""

    def setUp(self):
        self.user = User.objects.create_user(username="window-user")
        self.client.force_login(self.user)
        # in_window filters by the project's own start_date/last_updated window
        self.project = Projects.objects.create(
            user=self.user,
            name="Windowed",
            start_date=datetime(2025, 1, 5).date(),
            last_updated=datetime(2025, 1, 20).date(),
        )
        start = timezone.make_aware(datetime(2025, 1, 10, 9, 0))
        Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=start,
            end_time=start + timedelta(hours=1),
            is_active=False,
        )

    def test_projects_grouped_accepts_date_window(self):
        response = self.client.get(
            "/api/projects/grouped/",
            {"start_date": "01-01-2025", "end_date": "01-31-2025"},
        )
        self.assertEqual(response.status_code, 200)
        grouped = response.json()
        self.assertIn("Windowed", grouped["projects"]["active"])

    def test_projects_grouped_date_window_excludes_outside(self):
        response = self.client.get(
            "/api/projects/grouped/",
            {"start_date": "02-01-2025", "end_date": "02-28-2025"},
        )
        self.assertEqual(response.status_code, 200)
        grouped = response.json()
        self.assertEqual(grouped["projects"]["active"], [])

    def test_list_projects_accepts_date_window(self):
        response = self.client.get(
            "/api/list_projects/",
            {"start_date": "01-01-2025", "end_date": "01-31-2025"},
        )
        self.assertEqual(response.status_code, 200)
