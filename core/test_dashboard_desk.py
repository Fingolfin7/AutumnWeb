"""Tests for the Focus Desk dashboard port (UI_REDESIGN.md chunk 2b).

Two things here are easy to get subtly wrong and impossible to spot in a
screenshot: the hero timer's server-rendered first frame must match what
dashboard_desk.js paints a second later, and the start card's quick-start
chips must not offer to start a timer that is already running.
"""

from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.models import Context, Projects, Sessions, SubProjects
from core.services.dashboard import (
    build_quick_starts,
    get_recent_dashboard_sessions,
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


class QuickStartTests(DashboardTestCase):
    def test_repeated_work_on_one_combination_offers_one_chip(self):
        recent = [self._session(self.atlas, 10, subs=["auth"]),
                  self._session(self.atlas, 90, subs=["auth"])]
        self.assertEqual(len(build_quick_starts(recent, [])), 1)


    def test_a_combination_already_running_is_not_offered(self):
        """Offering to start a timer that is on the clock is pure noise."""
        recent = [self._session(self.atlas, 10, subs=["auth"]),
                  self._session(self.autumn, 20, subs=["ui"])]
        running = [self._timer(self.atlas, subs=["auth"])]

        quick_starts = build_quick_starts(recent, running)

        self.assertEqual([s.project.name for s in quick_starts], ["Autumn"])
