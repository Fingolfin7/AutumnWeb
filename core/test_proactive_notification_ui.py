from datetime import date, datetime, time, timedelta, timezone as dt_timezone

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import NotificationPreference, Projects, ScheduledReminder, SubProjects
from core.services import CommitmentEditService, SessionMutationService
from core.services.proactive_notifications import create_scheduled_reminder


UTC = dt_timezone.utc


class ProactiveNotificationUITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "notification-ui", "notification-ui@example.test", "password"
        )
        self.other = User.objects.create_user(
            "notification-other", "notification-other@example.test", "password"
        )
        self.user.profile.timezone = "Europe/Prague"
        self.user.profile.save(update_fields=["timezone"])
        self.project = Projects.objects.create(user=self.user, name="Gym")
        self.subproject = SubProjects.objects.create(
            user=self.user, parent_project=self.project, name="Push day"
        )
        self.foreign_project = Projects.objects.create(user=self.other, name="Private")
        self.client.force_login(self.user)

    def schedule(self, **overrides):
        local_date = timezone.localdate() + timedelta(days=3)
        values = {
            "user": self.user,
            "project": self.project,
            "subproject": self.subproject,
            "local_date": local_date,
            "local_time": time(18, 30),
            "cadence": "weekly",
            "message": "Time to start gym",
        }
        values.update(overrides)
        return create_scheduled_reminder(**values)

    def test_notifications_requires_login_and_renders_product_contract(self):
        self.client.logout()
        response = self.client.get(reverse("notifications"))
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.user)
        response = self.client.get(reverse("notifications"))
        self.assertContains(response, "How Autumn interrupts you")
        self.assertContains(response, "You planned CMG prep for 18:30.")
        self.assertContains(response, "Exercise: 1 session remaining; period ends Sunday.")
        self.assertContains(response, "Nothing scheduled for the next seven days.")
        self.assertTrue(NotificationPreference.objects.filter(user=self.user).exists())

    def test_preference_post_schedules_enabled_categories_and_rejects_early_check(self):
        response = self.client.post(
            reverse("notifications"),
            {
                "action": "save_preferences",
                "scheduled_reminders_enabled": "on",
                "commitment_checks_enabled": "on",
                "weekly_review_enabled": "on",
                "commitment_check_time": "17:59",
                "weekly_review_weekday": "0",
                "weekly_review_time": "09:00",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "18:00")

        response = self.client.post(
            reverse("notifications"),
            {
                "action": "save_preferences",
                "scheduled_reminders_enabled": "on",
                "commitment_checks_enabled": "on",
                "weekly_review_enabled": "on",
                "commitment_check_time": "18:30",
                "weekly_review_weekday": "0",
                "weekly_review_time": "09:00",
            },
        )
        self.assertRedirects(response, reverse("notifications"))
        preference = NotificationPreference.objects.get(user=self.user)
        self.assertIsNotNone(preference.next_commitment_check_at)
        self.assertIsNotNone(preference.next_weekly_review_at)

    def test_schedule_create_is_owned_and_edit_uses_optimistic_version(self):
        first_date = timezone.localdate() + timedelta(days=4)
        response = self.client.post(
            reverse("notifications"),
            {
                "action": "create_schedule",
                "project": self.foreign_project.pk,
                "local_date": first_date.isoformat(),
                "local_time": "18:30",
                "cadence": "once",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ScheduledReminder.objects.exists())

        response = self.client.post(
            reverse("notifications"),
            {
                "action": "create_schedule",
                "project": self.project.pk,
                "subproject": self.subproject.pk,
                "local_date": first_date.isoformat(),
                "local_time": "18:30",
                "cadence": "weekly",
                "message": "Time to start gym",
            },
        )
        self.assertRedirects(response, reverse("notifications"))
        reminder = ScheduledReminder.objects.get()

        response = self.client.post(
            reverse("edit_scheduled_reminder", args=[reminder.pk]),
            {
                "project": self.project.pk,
                "subproject": self.subproject.pk,
                "local_date": (first_date + timedelta(days=1)).isoformat(),
                "local_time": "19:00",
                "cadence": "weekly",
                "message": "Changed",
                "version": reminder.version - 1,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "changed in another tab")
        reminder.refresh_from_db()
        self.assertEqual(reminder.message, "Time to start gym")

    def test_snooze_and_cancel_are_owned_csrf_protected_posts(self):
        reminder = self.schedule()
        foreign = self.schedule(user=self.other, project=self.foreign_project, subproject=None)
        self.assertEqual(
            self.client.get(reverse("snooze_scheduled_reminder", args=[foreign.pk])).status_code,
            404,
        )

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        response = csrf_client.post(
            reverse("snooze_scheduled_reminder", args=[reminder.pk]),
            {"version": reminder.version, "choice": "15m"},
        )
        self.assertEqual(response.status_code, 403)

        response = self.client.post(
            reverse("snooze_scheduled_reminder", args=[reminder.pk]),
            {"version": reminder.version, "choice": "15m"},
        )
        self.assertRedirects(response, reverse("notifications"))
        reminder.refresh_from_db()
        self.assertIsNotNone(reminder.snoozed_until)

        response = self.client.post(
            reverse("cancel_scheduled_reminder", args=[reminder.pk]),
            {"version": reminder.version},
        )
        self.assertRedirects(response, reverse("notifications"))
        reminder.refresh_from_db()
        self.assertFalse(reminder.active)

    def test_start_timer_prefill_only_accepts_owned_project_and_subproject(self):
        response = self.client.get(
            reverse("start_timer"),
            {"project_id": self.project.pk, "subproject_id": self.subproject.pk},
        )
        self.assertContains(response, 'value="Gym"')
        self.assertContains(response, f'data-initial-subproject-id="{self.subproject.pk}"')

        response = self.client.get(
            reverse("start_timer"), {"project_id": self.foreign_project.pk}
        )
        self.assertNotContains(response, 'value="Private"')

    def test_commitment_opt_in_only_appears_when_global_category_is_on(self):
        commitment = CommitmentEditService.create(
            self.user,
            {
                "aggregation_type": "project",
                "project": self.project,
                "commitment_type": "sessions",
                "period": "weekly",
                "start_date": timezone.localdate(),
                "target": 1,
                "banking_enabled": False,
                "max_balance": 0,
                "min_balance": 0,
            },
        )
        preference = NotificationPreference.objects.create(user=self.user)
        response = self.client.get(reverse("update_commitment", args=[commitment.pk]))
        self.assertNotContains(response, "Check this commitment in notifications")

        preference.commitment_checks_enabled = True
        preference.save(update_fields=["commitment_checks_enabled"])
        response = self.client.get(reverse("update_commitment", args=[commitment.pk]))
        self.assertContains(response, "Check this commitment in notifications")

    def test_weekly_review_uses_requested_completed_local_week(self):
        project_two = Projects.objects.create(user=self.user, name="CMG")
        # Europe/Prague is UTC+1 in January. These sessions end inside the
        # requested local week starting 5 January 2026.
        SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=datetime(2026, 1, 6, 9, tzinfo=UTC),
            end_time=datetime(2026, 1, 6, 10, tzinfo=UTC),
            is_active=False,
        )
        SessionMutationService.create_session(
            user=self.user,
            project=project_two,
            start_time=datetime(2026, 1, 8, 13, tzinfo=UTC),
            end_time=datetime(2026, 1, 8, 13, 30, tzinfo=UTC),
            is_active=False,
        )

        response = self.client.get(reverse("weekly_review"), {"week": "2026-01-05"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1h 30m")
        self.assertContains(response, "across 2 projects")
        self.assertContains(response, "Gym")
        self.assertContains(response, "CMG")
        self.assertContains(
            response,
            f'{reverse("start_timer")}?project_id={self.project.pk}',
        )
