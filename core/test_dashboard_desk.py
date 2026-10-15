"""Tests for the Focus Desk dashboard port (UI_REDESIGN.md chunk 2b).

Two things here are easy to get subtly wrong and impossible to spot in a
screenshot: the hero timer's server-rendered first frame must match what
dashboard_desk.js paints a second later, and the start card's quick-start
chips must not offer to start a timer that is already running.
"""

from datetime import datetime, timedelta, timezone as datetime_timezone
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from core.models import Context, Projects, Sessions, SubProjects
from core.templatetags.time_formats import hero_duration
from core.services.dashboard import (
    QUICK_START_LIMIT,
    build_quick_starts,
    get_recent_dashboard_sessions,
    select_recent_dashboard_sessions,
)


class HeroDurationTests(TestCase):
    """`hero_duration` and `heroParts()` in dashboard_desk.js are one format.

    If they drift, the hero timer visibly jumps on its first tick.
    """

    def test_sub_hour_durations_read_minutes_and_seconds(self):
        self.assertEqual(
            hero_duration(timedelta(minutes=43, seconds=18)),
            [{"value": 43, "unit": "minutes"}, {"value": 18, "unit": "seconds"}],
        )

    def test_hours_push_seconds_off_the_end(self):
        self.assertEqual(
            hero_duration(timedelta(hours=2, minutes=5, seconds=40)),
            [{"value": 2, "unit": "hours"}, {"value": 5, "unit": "minutes"}],
        )

    def test_days_push_minutes_off_the_end(self):
        self.assertEqual(
            hero_duration(timedelta(days=1, hours=3, minutes=9)),
            [{"value": 1, "unit": "day"}, {"value": 3, "unit": "hours"}],
        )

    def test_units_are_singular_at_one(self):
        self.assertEqual(
            hero_duration(timedelta(minutes=1, seconds=1)),
            [{"value": 1, "unit": "minute"}, {"value": 1, "unit": "second"}],
        )

    def test_plain_numbers_are_read_as_minutes(self):
        """Sessions.duration is a float count of minutes, not a timedelta."""
        self.assertEqual(
            hero_duration(90.0),
            [{"value": 1, "unit": "hour"}, {"value": 30, "unit": "minutes"}],
        )

    def test_a_fresh_timer_reads_zero_rather_than_blank(self):
        self.assertEqual(
            hero_duration(0),
            [{"value": 0, "unit": "minutes"}, {"value": 0, "unit": "seconds"}],
        )


class DashboardTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="finrod", password="pw")
        self.context = Context.objects.create(user=self.user, name="Work")
        self.atlas = Projects.objects.create(
            user=self.user, name="Atlas API", context=self.context
        )
        self.autumn = Projects.objects.create(
            user=self.user, name="Autumn", context=self.context
        )
        self.client.login(username="finrod", password="pw")

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
            user=self.user,
            project=project,
            start_time=timezone.now() - timedelta(minutes=10),
        )
        for name in subs:
            sub, _ = SubProjects.objects.get_or_create(
                user=self.user, parent_project=project, name=name
            )
            timer.subprojects.add(sub)
        return timer


class RecentDashboardSessionSelectionTests(DashboardTestCase):
    def _session_at(self, project, day, hour, minute=0, second=0):
        end = timezone.make_aware(
            datetime(2026, 7, day, hour, minute, second),
            timezone.get_current_timezone(),
        )
        return Sessions.objects.create(
            user=self.user,
            project=project,
            start_time=end - timedelta(minutes=30),
            end_time=end,
        )

    def _selected(self):
        return list(get_recent_dashboard_sessions(self.user))

    def test_three_to_five_sessions_on_newest_day_stay_on_that_day(self):
        newest = [
            self._session_at(self.atlas, 25, 15, index)
            for index in range(4)
        ]
        older = self._session_at(self.autumn, 24, 15)

        selected = self._selected()

        self.assertEqual(
            [session.id for session in selected],
            [session.id for session in reversed(newest)],
        )
        self.assertNotIn(older.id, [session.id for session in selected])

    def test_exactly_three_newest_sessions_do_not_expand(self):
        newest = [
            self._session_at(self.atlas, 25, 15, index)
            for index in range(3)
        ]
        self._session_at(self.autumn, 24, 15)

        selected = self._selected()

        self.assertEqual(
            [session.id for session in selected],
            [session.id for session in reversed(newest)],
        )

    def test_busy_newest_day_is_shown_in_full(self):
        newest = [
            self._session_at(self.atlas, 25, 15, index)
            for index in range(6)
        ]
        older = self._session_at(self.autumn, 24, 15)

        selected = self._selected()

        self.assertEqual(
            [session.id for session in selected],
            [session.id for session in reversed(newest)],
        )
        self.assertNotIn(older.id, [session.id for session in selected])

    def test_sparse_newest_day_expands_across_nonconsecutive_dates_to_five(self):
        newest = [
            self._session_at(self.atlas, 25, 15, index)
            for index in range(2)
        ]
        middle = [
            self._session_at(self.autumn, 21, 15, index)
            for index in range(2)
        ]
        oldest = [
            self._session_at(self.atlas, 10, 15, index)
            for index in range(2)
        ]

        selected = self._selected()

        self.assertEqual(
            [session.id for session in selected],
            [
                *[session.id for session in reversed(newest)],
                *[session.id for session in reversed(middle)],
                oldest[-1].id,
            ],
        )
        self.assertEqual(
            {timezone.localtime(session.end_time).date() for session in selected},
            {
                datetime(2026, 7, 25).date(),
                datetime(2026, 7, 21).date(),
                datetime(2026, 7, 10).date(),
            },
        )

    def test_sparse_activity_returns_all_available_sessions(self):
        newest = self._session_at(self.atlas, 25, 15)
        older = self._session_at(self.autumn, 10, 15)

        selected = self._selected()

        self.assertEqual(
            [session.id for session in selected], [newest.id, older.id]
        )

    def test_active_and_other_users_sessions_are_excluded(self):
        completed = self._session_at(self.atlas, 25, 15)
        Sessions.objects.create(
            user=self.user,
            project=self.autumn,
            start_time=timezone.now() - timedelta(minutes=10),
        )
        other_user = User.objects.create_user(
            username="other", email="other@example.com", password="pw"
        )
        other_project = Projects.objects.create(user=other_user, name="Other")
        Sessions.objects.create(
            user=other_user,
            project=other_project,
            start_time=timezone.now() - timedelta(minutes=20),
            end_time=timezone.now() - timedelta(minutes=5),
        )

        selected = self._selected()

        self.assertEqual([session.id for session in selected], [completed.id])

    def test_same_end_time_uses_id_as_stable_tiebreaker(self):
        first = self._session_at(self.atlas, 25, 15)
        second = self._session_at(self.autumn, 25, 15)
        sessions = Sessions.objects.filter(user=self.user).order_by(
            "-end_time", "-id"
        )

        selected = select_recent_dashboard_sessions(sessions)

        self.assertEqual([session.id for session in selected], [second.id, first.id])


class QuickStartTests(DashboardTestCase):
    def test_repeated_work_on_one_combination_offers_one_chip(self):
        recent = [self._session(self.atlas, 10, subs=["auth"]),
                  self._session(self.atlas, 90, subs=["auth"])]
        self.assertEqual(len(build_quick_starts(recent, [])), 1)

    def test_different_subprojects_are_different_chips(self):
        recent = [self._session(self.atlas, 10, subs=["auth"]),
                  self._session(self.atlas, 90, subs=["billing"])]
        self.assertEqual(len(build_quick_starts(recent, [])), 2)

    def test_a_combination_already_running_is_not_offered(self):
        """Offering to start a timer that is on the clock is pure noise."""
        recent = [self._session(self.atlas, 10, subs=["auth"]),
                  self._session(self.autumn, 20, subs=["ui"])]
        running = [self._timer(self.atlas, subs=["auth"])]

        quick_starts = build_quick_starts(recent, running)

        self.assertEqual([s.project.name for s in quick_starts], ["Autumn"])

    def test_the_chip_list_is_capped(self):
        recent = [
            self._session(self.atlas, index * 10, subs=[f"sub-{index}"])
            for index in range(1, QUICK_START_LIMIT + 4)
        ]
        self.assertEqual(len(build_quick_starts(recent, [])), QUICK_START_LIMIT)


class TimelineFragmentTests(DashboardTestCase):
    """The fragment endpoint serves both the range tabs and the live poll."""

    def test_fragment_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("timeline_fragment"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    @freeze_time("2026-09-20 12:00:00+02:00")
    def test_fragment_renders_the_timeline_alone(self):
        self._session(self.atlas, 10, subs=["auth"])

        response = self.client.get(reverse("timeline_fragment"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertContains(response, "data-timeline")
        self.assertContains(response, "Atlas API")
        # a fragment, not a page
        self.assertNotContains(response, "<html")
        self.assertNotContains(response, "desk-head")

    def test_the_range_parameter_selects_the_window(self):
        response = self.client.get(reverse("timeline_fragment"), {"range": "wk"})

        self.assertContains(response, 'data-timeline-range="wk"')
        self.assertContains(response, 'data-tlrange="wk"')

    def test_a_junk_range_falls_back_rather_than_failing(self):
        response = self.client.get(reverse("timeline_fragment"), {"range": "nonsense"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-timeline-range="today"')

    def test_the_fragment_carries_the_window_the_client_ticks_against(self):
        """dashboard_desk.js grows live blocks locally; without absolute
        window bounds it would have to poll instead."""
        response = self.client.get(reverse("timeline_fragment"))

        self.assertContains(response, "data-timeline-window")

    def test_a_running_timer_is_marked_for_client_side_ticking(self):
        self._timer(self.atlas, subs=["auth"])

        response = self.client.get(reverse("timeline_fragment"))

        self.assertContains(response, "data-live-block")
        self.assertContains(response, "data-start-iso")
        self.assertContains(response, "data-live-dur")

