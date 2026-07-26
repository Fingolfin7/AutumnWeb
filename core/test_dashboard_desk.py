"""Tests for the Focus Desk dashboard port (UI_REDESIGN.md chunk 2b).

Two things here are easy to get subtly wrong and impossible to spot in a
screenshot: the hero timer's server-rendered first frame must match what
dashboard_desk.js paints a second later, and the start card's quick-start
chips must not offer to start a timer that is already running.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Context, Projects, Sessions, SubProjects
from core.templatetags.time_formats import hero_duration
from core.views.dashboard import QUICK_START_LIMIT, build_quick_starts, greeting_for


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


class GreetingTests(TestCase):
    def test_greeting_follows_the_local_clock(self):
        day = timezone.localtime(timezone.now()).replace(minute=0, second=0, microsecond=0)
        self.assertEqual(greeting_for(day.replace(hour=8)), "Good morning")
        self.assertEqual(greeting_for(day.replace(hour=14)), "Good afternoon")
        self.assertEqual(greeting_for(day.replace(hour=21)), "Good evening")


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


class DashboardRendersFocusDeskTests(DashboardTestCase):
    def test_dashboard_uses_the_focus_desk_shell_only(self):
        """No page may load both stylesheets — that is the whole migration."""
        response = self.client.get(reverse("home"))

        self.assertTemplateUsed(response, "core/base_fd.html")
        self.assertContains(response, "core/css/focus_desk.css")
        self.assertNotContains(response, "core/css/style.css")

    def test_dashboard_supplies_the_day_timeline(self):
        self._session(self.atlas, 10, subs=["auth"])

        response = self.client.get(reverse("home"))

        self.assertIn("timeline", response.context)
        self.assertEqual(
            [lane["project"].name for lane in response.context["timeline"]["lanes"]],
            ["Atlas API"],
        )
        self.assertContains(response, "fd-tl-lane")

    def test_an_untracked_day_renders_the_axis_and_an_empty_state(self):
        response = self.client.get(reverse("home"))

        self.assertEqual(response.context["timeline"]["lanes"], [])
        self.assertContains(response, "fd-tl-empty")
        self.assertNotContains(response, "fd-tl-lane")

    def test_running_timers_render_as_focus_cards(self):
        self._timer(self.atlas, subs=["auth"])

        response = self.client.get(reverse("home"))

        self.assertContains(response, "focus-card")
        self.assertContains(response, "Atlas API")
        # start card is always present alongside the running ones
        self.assertContains(response, "focus-card--start")

    def test_quick_start_chips_post_the_project_and_subprojects(self):
        self._session(self.atlas, 10, subs=["auth"])

        response = self.client.get(reverse("home"))

        self.assertEqual(
            [s.project.name for s in response.context["quick_starts"]], ["Atlas API"]
        )
        self.assertContains(response, 'name="project" value="Atlas API"')
        self.assertContains(response, 'name="subprojects" value="auth"')
