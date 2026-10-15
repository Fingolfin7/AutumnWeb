"""Notification preferences, schedules and the weekly review through /api/v2/.

Ported from the old Notifications and Weekly review page tests
(core.test_proactive_notification_ui); the React pages call these endpoints.
"""

from datetime import datetime, time, timedelta, timezone as dt_timezone

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (
    Context,
    NotificationPreference,
    Projects,
    ScheduledReminder,
    SubProjects,
    Tag,
)
from core.services import SessionMutationService
from core.services.proactive_notifications import create_scheduled_reminder

UTC = dt_timezone.utc
PREFERENCES = "/api/v2/notifications/preferences/"
SCHEDULES = "/api/v2/notifications/schedules/"


class NotificationsApiTestCase(TestCase):
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
        self.other_subproject = SubProjects.objects.create(
            user=self.user, parent_project=self.project, name="Pull day"
        )
        self.foreign_project = Projects.objects.create(user=self.other, name="Private")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def schedule(self, **overrides):
        values = {
            "user": self.user,
            "project": self.project,
            "subprojects": [self.subproject],
            "local_date": timezone.localdate() + timedelta(days=3),
            "local_time": time(18, 30),
            "cadence": "weekly",
            "message": "Time to start gym",
        }
        values.update(overrides)
        return create_scheduled_reminder(**values)

    def body(self, **overrides):
        values = {
            "local_date": (timezone.localdate() + timedelta(days=4)).isoformat(),
            "local_time": "18:30",
            "cadence": "once",
        }
        values.update(overrides)
        return values


class PreferencesTests(NotificationsApiTestCase):
    def test_requires_login_and_creates_the_preference_row_on_first_read(self):
        self.assertEqual(Client().get(PREFERENCES).status_code in (401, 403), True)
        self.assertFalse(NotificationPreference.objects.filter(user=self.user).exists())
        response = self.client.get(PREFERENCES)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(NotificationPreference.objects.filter(user=self.user).exists())
        for key in ("commitment_checks_enabled", "weekly_review_enabled", "scheduled_reminders_enabled"):
            self.assertIn(key, response.json())

    def test_a_commitment_check_earlier_than_18_00_is_refused(self):
        response = self.client.patch(
            PREFERENCES,
            {
                "scheduled_reminders_enabled": True,
                "commitment_checks_enabled": True,
                "weekly_review_enabled": True,
                "commitment_check_time": "17:59",
                "weekly_review_weekday": 0,
                "weekly_review_time": "09:00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("commitment_check_time", response.json()["error"]["details"])

    def test_enabling_categories_schedules_their_next_runs(self):
        response = self.client.patch(
            PREFERENCES,
            {
                "scheduled_reminders_enabled": True,
                "commitment_checks_enabled": True,
                "weekly_review_enabled": True,
                "commitment_check_time": "18:30",
                "weekly_review_weekday": 0,
                "weekly_review_time": "09:00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        preference = NotificationPreference.objects.get(user=self.user)
        self.assertIsNotNone(preference.next_commitment_check_at)
        self.assertIsNotNone(preference.next_weekly_review_at)
        self.assertIsNotNone(response.json()["next_commitment_check_at"])
        self.assertIsNotNone(response.json()["next_weekly_review_at"])


class ScheduleTests(NotificationsApiTestCase):
    def test_nothing_is_scheduled_at_first(self):
        payload = self.client.get(SCHEDULES).json()
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["upcoming"], [])

    def test_a_project_schedule_keeps_all_its_subprojects(self):
        response = self.client.post(
            SCHEDULES,
            self.body(
                target="project",
                project=self.project.pk,
                subprojects=[self.subproject.pk, self.other_subproject.pk],
                cadence="weekly",
                message="Time to start gym",
            ),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        reminder = ScheduledReminder.objects.get()
        self.assertCountEqual(
            reminder.subprojects.values_list("pk", flat=True),
            [self.subproject.pk, self.other_subproject.pk],
        )
        self.assertEqual(
            {row["id"] for row in response.json()["subprojects"]},
            {self.subproject.pk, self.other_subproject.pk},
        )

    def test_another_users_project_is_refused(self):
        response = self.client.post(
            SCHEDULES, self.body(target="project", project=self.foreign_project.pk), format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ScheduledReminder.objects.exists())

    def test_edits_use_the_optimistic_version(self):
        reminder = self.schedule()
        stale = self.client.patch(
            f"{SCHEDULES}{reminder.pk}",
            {"message": "Changed", "version": reminder.version - 1},
            format="json",
        )
        self.assertIn(stale.status_code, (400, 409))
        self.assertIn("changed in another tab", stale.content.decode())
        reminder.refresh_from_db()
        self.assertEqual(reminder.message, "Time to start gym")

        fresh = self.client.patch(
            f"{SCHEDULES}{reminder.pk}",
            {"message": "Changed", "version": reminder.version},
            format="json",
        )
        self.assertEqual(fresh.status_code, 200, fresh.content)
        reminder.refresh_from_db()
        self.assertEqual(reminder.message, "Changed")

    def test_a_context_target_drops_any_project_and_subprojects(self):
        context = Context.objects.create(user=self.user, name="Exercise")
        response = self.client.post(
            SCHEDULES,
            # A stray project/subproject selection must not survive the choice.
            self.body(
                target="context",
                context=context.pk,
                project=self.project.pk,
                subprojects=[self.subproject.pk],
            ),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        reminder = ScheduledReminder.objects.get()
        self.assertIsNone(reminder.project_id)
        self.assertIsNone(reminder.tag_id)
        self.assertEqual(reminder.context_id, context.pk)
        self.assertEqual(list(reminder.subprojects.all()), [])
        self.assertEqual(response.json()["target"], "context")
        self.assertEqual(response.json()["target_resource"]["name"], "Exercise")

    def test_switching_the_target_restores_or_clears_subprojects(self):
        context = Context.objects.create(user=self.user, name="Exercise")
        tag = Tag.objects.create(user=self.user, name="Deep work")
        reminder = self.schedule(project=None, context=context, subprojects=None, cadence="once")
        url = f"{SCHEDULES}{reminder.pk}"

        to_project = self.client.patch(
            url,
            {
                "target": "project",
                "project": self.project.pk,
                "subprojects": [self.subproject.pk, self.other_subproject.pk],
                "version": reminder.version,
            },
            format="json",
        )
        self.assertEqual(to_project.status_code, 200, to_project.content)
        reminder.refresh_from_db()
        self.assertIsNone(reminder.context_id)
        self.assertCountEqual(
            reminder.subprojects.values_list("pk", flat=True),
            [self.subproject.pk, self.other_subproject.pk],
        )

        to_tag = self.client.patch(
            url,
            {
                "target": "tag",
                "tag": tag.pk,
                "subprojects": [self.subproject.pk],
                "version": reminder.version,
            },
            format="json",
        )
        self.assertEqual(to_tag.status_code, 200, to_tag.content)
        reminder.refresh_from_db()
        self.assertEqual(reminder.tag_id, tag.pk)
        self.assertIsNone(reminder.project_id)
        self.assertEqual(list(reminder.subprojects.all()), [])

    def test_a_context_target_needs_a_context(self):
        response = self.client.post(SCHEDULES, self.body(target="context"), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Choose a context.", response.content.decode())
        self.assertFalse(ScheduledReminder.objects.exists())

    def test_a_context_owned_by_another_account_is_refused(self):
        theirs = Context.objects.create(user=self.other, name="Theirs")
        response = self.client.post(
            SCHEDULES, self.body(target="context", context=theirs.pk), format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ScheduledReminder.objects.exists())

    def test_snooze_and_cancel_are_owned_and_csrf_protected(self):
        reminder = self.schedule()
        foreign = self.schedule(user=self.other, project=self.foreign_project, subprojects=None)
        snooze = f"{SCHEDULES}{foreign.pk}/snooze/"
        self.assertEqual(
            self.client.post(snooze, {"choice": "15m", "version": foreign.version}, format="json").status_code,
            404,
        )

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        response = csrf_client.post(
            f"{SCHEDULES}{reminder.pk}/snooze/",
            {"version": reminder.version, "choice": "15m"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

        response = self.client.post(
            f"{SCHEDULES}{reminder.pk}/snooze/",
            {"version": reminder.version, "choice": "15m"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        reminder.refresh_from_db()
        self.assertIsNotNone(reminder.snoozed_until)

        response = self.client.delete(
            f"{SCHEDULES}{reminder.pk}", {"version": reminder.version}, format="json"
        )
        self.assertEqual(response.status_code, 204)
        reminder.refresh_from_db()
        self.assertFalse(reminder.active)


class WeeklyReviewTests(NotificationsApiTestCase):
    def test_review_covers_the_requested_local_week(self):
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
        # Outside the window: must not count.
        SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=datetime(2026, 1, 20, 9, tzinfo=UTC),
            end_time=datetime(2026, 1, 20, 10, tzinfo=UTC),
            is_active=False,
        )

        data = self.client.get("/api/v2/reports/weekly-review/", {"week": "2026-01-05"}).json()

        self.assertEqual(data["week_start"], "2026-01-05")
        self.assertEqual(data["total_minutes"], 90)
        self.assertEqual(data["duration_label"], "1h 30m")
        self.assertEqual(data["project_count"], 2)
        self.assertEqual(data["session_count"], 2)
        self.assertEqual({row["project_name"] for row in data["per_project"]}, {"Gym", "CMG"})

    def test_another_users_sessions_are_not_counted(self):
        SessionMutationService.create_session(
            user=self.other,
            project=self.foreign_project,
            start_time=datetime(2026, 1, 6, 9, tzinfo=UTC),
            end_time=datetime(2026, 1, 6, 10, tzinfo=UTC),
            is_active=False,
        )
        data = self.client.get("/api/v2/reports/weekly-review/", {"week": "2026-01-05"}).json()
        self.assertEqual(data["session_count"], 0)
        self.assertEqual(data["total_minutes"], 0)
