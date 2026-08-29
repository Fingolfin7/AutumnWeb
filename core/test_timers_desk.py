"""Tests for the Focus Desk timers pages (UI_REDESIGN.md chunk 6).

The risk on these pages is not layout — it is the JavaScript contract. Three
scripts build or drive markup this template only supplies hooks for, and a
renamed id fails silently in the browser while every Python test still passes.
"""

from datetime import datetime, timedelta

from freezegun import freeze_time

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Context, Projects, Sessions, SubProjects, TimerReminder


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
            "data-timer-stop",
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
        self.assertContains(response, "data-timer-note-draft")


class TimerPageContentTests(TimerPagesTestCase):
    def test_stop_page_datetime_inputs_include_seconds(self):
        started_at = timezone.make_aware(datetime(2026, 8, 5, 9, 7, 43))
        timer = Sessions.objects.create(
            user=self.user,
            project=self.atlas,
            start_time=started_at,
        )

        with freeze_time("2026-08-05 10:11:29+00:00"):
            response = self.client.get(reverse("stop_timer", args=[timer.id]))
            expected_end = timezone.localtime(timezone.now()).strftime(
                "%Y-%m-%dT%H:%M:%S"
            )

        self.assertContains(response, 'step="1"', count=2)
        self.assertContains(response, started_at.strftime("%Y-%m-%dT%H:%M:%S"))
        self.assertContains(response, expected_end)

    @freeze_time("2026-08-05 10:11:29+00:00")
    def test_stop_without_explicit_times_preserves_second_accuracy(self):
        started_at = timezone.make_aware(datetime(2026, 8, 5, 9, 7, 43))
        timer = Sessions.objects.create(
            user=self.user,
            project=self.atlas,
            start_time=started_at,
        )

        response = self.client.post(reverse("stop_timer", args=[timer.id]))

        self.assertRedirects(response, reverse("timers"))
        timer.refresh_from_db()
        self.assertEqual(timer.start_time, started_at)
        self.assertEqual(timer.end_time.second, 29)
        self.assertEqual(timer.end_time.microsecond, 0)

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


class TimerReminderPageTests(TimerPagesTestCase):
    def test_start_form_exposes_the_shared_reminder_contract(self):
        response = self.client.get(reverse("start_timer"))

        self.assertContains(response, 'name="reminder_mode"')
        self.assertContains(response, 'value="after"')
        self.assertContains(response, 'value="interval"')
        self.assertContains(response, 'name="reminder_amount"')
        self.assertContains(response, 'name="reminder_unit"')
        self.assertContains(response, 'name="reminder_at"')
        self.assertContains(response, 'name="notify_on_auto_stop"')
        self.assertContains(response, self.user.profile.timezone)
        self.assertContains(response, "data-rm-timezone")

    def test_start_timer_creates_one_shot_reminder_and_auto_stop_preference(self):
        response = self.client.post(
            reverse("start_timer"),
            {
                "project": self.atlas.name,
                "reminder_mode": "after",
                "reminder_amount": "20",
                "reminder_unit": "minutes",
                "reminder_message": "Check in",
                "notify_on_auto_stop": "1",
            },
        )

        self.assertRedirects(response, reverse("timers"))
        session = Sessions.objects.get(user=self.user, end_time__isnull=True)
        self.assertTrue(session.notify_on_auto_stop)
        reminder = TimerReminder.objects.get(session=session)
        self.assertEqual(reminder.mode, "after")
        self.assertIsNone(reminder.interval_seconds)
        self.assertEqual(
            int((reminder.next_fire_at - session.start_time).total_seconds()),
            20 * 60,
        )
        self.assertEqual(reminder.message, "Check in")

    def test_start_timer_creates_interval_reminder(self):
        self.client.post(
            reverse("start_timer"),
            {
                "project": self.atlas.name,
                "reminder_mode": "interval",
                "reminder_amount": "5",
                "reminder_unit": "minutes",
            },
        )

        session = Sessions.objects.get(user=self.user, end_time__isnull=True)
        reminder = TimerReminder.objects.get(session=session)
        self.assertEqual(reminder.mode, "interval")
        self.assertEqual(reminder.interval_seconds, 5 * 60)

    def test_start_timer_at_uses_profile_timezone(self):
        self.user.profile.timezone = "America/New_York"
        self.user.profile.save(update_fields=["timezone"])

        response = self.client.post(
            reverse("start_timer"),
            {
                "project": self.atlas.name,
                "reminder_mode": "at",
                "reminder_at": "2030-08-05T15:30",
            },
        )

        self.assertRedirects(response, reverse("timers"))
        session = Sessions.objects.get(user=self.user, end_time__isnull=True)
        reminder = TimerReminder.objects.get(session=session)
        self.assertEqual(reminder.mode, "at")
        self.assertEqual(
            reminder.next_fire_at.isoformat(), "2030-08-05T19:30:00+00:00"
        )

    def test_start_timer_rejects_a_past_at_reminder_without_creating_a_timer(self):
        response = self.client.post(
            reverse("start_timer"),
            {
                "project": self.atlas.name,
                "reminder_mode": "at",
                "reminder_at": "2020-01-01T12:00",
            },
            follow=True,
        )

        self.assertContains(response, "Reminder time must be in the future")
        self.assertFalse(Sessions.objects.filter(user=self.user).exists())

    def test_active_fragment_renders_prefetched_reminder_with_cancel_url(self):
        timer = self._timer()
        TimerReminder.objects.create(
            session=timer,
            mode="after",
            next_fire_at=timezone.now() + timedelta(minutes=5),
        )

        with self.assertNumQueries(7):
            response = self.client.get(
                reverse("active_timers_fragment"), {"surface": "timers"}
            )

        self.assertContains(response, "Once after")
        self.assertContains(
            response,
            reverse(
                "cancel_timer_reminder",
                args=[timer.id, timer.reminders.first().id],
            ),
        )

    def test_dashboard_first_paint_includes_active_reminders(self):
        timer = self._timer()
        reminder = TimerReminder.objects.create(
            session=timer,
            mode="after",
            next_fire_at=timezone.now() + timedelta(minutes=5),
            message="First-paint reminder",
        )

        response = self.client.get(reverse("home"))

        self.assertContains(response, "First-paint reminder")
        self.assertContains(
            response,
            reverse("cancel_timer_reminder", args=[timer.id, reminder.id]),
        )

    def test_cancel_reminder_is_owned_and_removes_active_rule(self):
        timer = self._timer()
        reminder = TimerReminder.objects.create(
            session=timer,
            mode="at",
            next_fire_at=timezone.now() + timedelta(minutes=5),
        )

        response = self.client.post(
            reverse("cancel_timer_reminder", args=[timer.id, reminder.id])
        )

        self.assertEqual(response.status_code, 200)
        reminder.refresh_from_db()
        self.assertFalse(reminder.active)
