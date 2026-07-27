"""Tests for the Focus Desk timers pages (UI_REDESIGN.md chunk 6).

The risk on these pages is not layout — it is the JavaScript contract. Three
scripts build or drive markup this template only supplies hooks for, and a
renamed id fails silently in the browser while every Python test still passes.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Context, Projects, Sessions, SubProjects


class TimerPagesTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="finrod", email="finrod@example.com", password="pw"
        )
        self.context = Context.objects.create(user=self.user, name="Work")
        self.atlas = Projects.objects.create(
            user=self.user, name="Atlas API", context=self.context
        )
        self.sub = SubProjects.objects.create(
            user=self.user, parent_project=self.atlas, name="auth"
        )
        self.client.login(username="finrod", password="pw")

    def _timer(self):
        timer = Sessions.objects.create(
            user=self.user,
            project=self.atlas,
            start_time=timezone.now() - timedelta(minutes=12),
        )
        timer.subprojects.add(self.sub)
        return timer


class TimerShellTests(TimerPagesTestCase):
    def test_every_timer_page_uses_the_focus_desk_shell_only(self):
        timer = self._timer()
        pages = [
            reverse("timers"),
            reverse("start_timer"),
            reverse("stop_timer", args=[timer.id]),
            reverse("remove_timer", args=[timer.id]),
        ]

        for url in pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "core/base.html")
                self.assertContains(response, "core/css/focus_desk.css")
                self.assertNotContains(response, "core/css/style.css")


class ScriptContractTests(TimerPagesTestCase):
    """Every hook below is read by a script; renaming one breaks it silently."""

    def test_start_form_keeps_the_ids_timer_search_projects_drives(self):
        html = self.client.get(reverse("start_timer")).content.decode()

        for hook in (
            'id="project-search"',
            'id="project-search-results"',
            'id="list_subs"',
            'id="subproject_options"',
            'id="pick-subprojects"',
            'id="select-all-block"',
            'id="select-all"',
            'id="stop-after-amount"',
            'id="stop-after-unit"',
            'id="start-timer"',
            "data-stop-after-preset",
            "data-start-timer-summary",
        ):
            with self.subTest(hook=hook):
                self.assertIn(hook, html)

    def test_the_submit_button_starts_disabled(self):
        """It is enabled by script once a project is chosen; shipping it
        enabled would let you post an empty form."""
        self.assertContains(self.client.get(reverse("start_timer")), "disabled")

    def test_running_cards_keep_the_note_editor_hooks(self):
        self._timer()

        html = self.client.get(reverse("timers")).content.decode()

        for hook in (
            "data-timer-note-editor",
            "data-timer-note-input",
            "data-timer-note-save",
            "data-timer-note-status",
            "data-timer-note-stamp",
            'data-dirty="false"',
            "data-save-url",
        ):
            with self.subTest(hook=hook):
                self.assertIn(hook, html)

    def test_the_polled_fragment_keeps_its_polling_attributes(self):
        self._timer()

        response = self.client.get(
            reverse("active_timers_fragment"), {"surface": "timers"}
        )

        self.assertContains(response, 'id="active-timers"')
        self.assertContains(response, 'data-timer-surface="timers"')
        self.assertContains(response, "data-refresh-url")
        self.assertContains(response, "data-timer-id")
        self.assertContains(response, "data-start-time")

    def test_stop_page_keeps_the_allocation_editor_items(self):
        timer = self._timer()

        response = self.client.get(reverse("stop_timer", args=[timer.id]))

        self.assertContains(response, "data-allocation-editor")
        self.assertContains(response, "data-allocation-item")
        self.assertContains(response, 'data-subproject-name="auth"')


class TimerPageContentTests(TimerPagesTestCase):
    def test_the_deck_always_offers_a_way_to_start(self):
        """Even with timers running — the start card is not an empty state."""
        self._timer()

        response = self.client.get(reverse("timers"))

        self.assertContains(response, "focus-card--start")
        self.assertContains(response, reverse("start_timer"))

    def test_remove_points_at_stop_as_the_non_destructive_option(self):
        timer = self._timer()

        response = self.client.get(reverse("remove_timer", args=[timer.id]))

        self.assertContains(response, reverse("stop_timer", args=[timer.id]))
