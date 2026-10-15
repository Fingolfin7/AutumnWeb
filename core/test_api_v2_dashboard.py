"""What the Home page shows, read through GET /api/v2/dashboard/ and /reports/timeline/.

These cases came from the server-rendered dashboard's tests (core.tests
DashboardViewTests and core.test_dashboard_desk): the React Home page renders
this payload and nothing else.
"""

from datetime import datetime, timedelta, timezone as datetime_timezone
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time

from core.models import Commitment, Context, Projects, Sessions, SubProjects


class DashboardApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="finrod", password="pw")
        self.context = Context.objects.create(user=self.user, name="Work")
        self.atlas = Projects.objects.create(user=self.user, name="Atlas API", context=self.context)
        self.autumn = Projects.objects.create(user=self.user, name="Autumn", context=self.context)
        self.client.force_login(self.user)

    def _session(self, project, minutes_ago, length=30, subs=()):
        end = timezone.now() - timedelta(minutes=minutes_ago)
        session = Sessions.objects.create(
            user=self.user,
            project=project,
            start_time=end - timedelta(minutes=length),
            end_time=end,
        )
        for name in subs:
            sub, _ = SubProjects.objects.get_or_create(
                user=self.user, parent_project=project, name=name
            )
            session.subprojects.add(sub)
        return session

    def _timer(self, project, subs=()):
        timer = Sessions.objects.create(
            user=self.user, project=project, start_time=timezone.now() - timedelta(minutes=10)
        )
        for name in subs:
            sub, _ = SubProjects.objects.get_or_create(
                user=self.user, parent_project=project, name=name
            )
            timer.subprojects.add(sub)
        return timer

    def _dashboard(self, **params):
        response = self.client.get("/api/v2/dashboard/", params)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_requires_login(self):
        self.client.logout()
        self.assertIn(self.client.get("/api/v2/dashboard/").status_code, (401, 403))

    def test_quick_stats_and_streak_are_present(self):
        payload = self._dashboard()
        for key in ("today_total", "week_total", "active_timers_count"):
            self.assertEqual(payload[key], 0)
        self.assertIn("current_streak", payload["daily_streak"])
        self.assertIn("recent_days", payload["daily_streak"])

    def test_active_timers_are_counted_and_listed(self):
        timer = self._timer(self.atlas, subs=["auth"])
        payload = self._dashboard()
        self.assertEqual(payload["active_timers_count"], 1)
        self.assertEqual([row["id"] for row in payload["active_timers"]], [timer.pk])

    def test_commitments_come_with_progress_and_streak(self):
        Commitment.objects.create(
            user=self.user, project=self.atlas, commitment_type="time", period="weekly", target=300
        )
        payload = self._dashboard()
        self.assertEqual(len(payload["commitments"]), 1)
        item = payload["commitments"][0]
        self.assertIn("percentage", item["progress"])
        self.assertIn("streak", item)
        self.assertEqual(item["commitment"]["target"]["name"], "Atlas API")
        self.assertEqual(item["commitment"]["period"], "weekly")

    def test_summary_windows_follow_the_users_local_day(self):
        self.user.profile.timezone = "Pacific/Kiritimati"
        self.user.profile.save(update_fields=["timezone"])
        # Monday 00:30 in Kiritimati, while the UTC date is still Sunday.
        now = datetime(2026, 1, 4, 10, 30, tzinfo=datetime_timezone.utc)
        Sessions.objects.create(
            user=self.user,
            project=self.atlas,
            start_time=now - timedelta(minutes=40),
            end_time=now - timedelta(minutes=10),
        )
        Sessions.objects.create(
            user=self.user,
            project=self.autumn,
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
        )
        with patch("core.services.dashboard.timezone.now", return_value=now):
            payload = self._dashboard()
        self.assertEqual(payload["today_total"], 30.0)
        self.assertEqual(payload["week_total"], 30.0)

    @freeze_time("2026-09-20 12:00:00+02:00")
    def test_dashboard_supplies_the_day_timeline(self):
        self._session(self.atlas, 10, subs=["auth"])
        timeline = self._dashboard()["timeline"]
        self.assertEqual([lane["project"]["name"] for lane in timeline["lanes"]], ["Atlas API"])

    def test_an_untracked_day_has_an_axis_and_no_lanes(self):
        timeline = self._dashboard()["timeline"]
        self.assertEqual(timeline["lanes"], [])
        self.assertTrue(timeline["ticks"])

    @freeze_time("2026-09-20 12:00:00+02:00")
    def test_timeline_endpoint_shows_a_running_timer_as_live(self):
        self._timer(self.atlas, subs=["auth"])
        response = self.client.get("/api/v2/reports/timeline/")
        self.assertEqual(response.status_code, 200)
        [lane] = response.json()["lanes"]
        self.assertEqual(lane["project"]["name"], "Atlas API")
        self.assertTrue(lane["blocks"][0]["is_live"])
        self.assertGreater(lane["live_minutes"], 0)
        self.assertIn("window_start", response.json())
        self.assertIn("window_end", response.json())

    def test_quick_starts_offer_the_project_and_subprojects(self):
        self._session(self.atlas, 10, subs=["auth"])
        [chip] = self._dashboard()["quick_starts"]
        self.assertEqual(chip["project"]["name"], "Atlas API")
        self.assertEqual([sub["name"] for sub in chip["subprojects"]], ["auth"])

    def test_a_combination_already_running_is_not_offered(self):
        self._session(self.atlas, 10, subs=["auth"])
        self._session(self.autumn, 20, subs=["ui"])
        self._timer(self.atlas, subs=["auth"])
        chips = self._dashboard()["quick_starts"]
        self.assertEqual([chip["project"]["name"] for chip in chips], ["Autumn"])

    def test_other_accounts_are_never_included(self):
        other = User.objects.create_user(username="other", email="other@example.com", password="pw")
        foreign = Projects.objects.create(user=other, name="Foreign")
        Sessions.objects.create(user=other, project=foreign, start_time=timezone.now() - timedelta(minutes=5))
        payload = self._dashboard()
        self.assertEqual(payload["active_timers_count"], 0)
        self.assertEqual(payload["active_timers"], [])
