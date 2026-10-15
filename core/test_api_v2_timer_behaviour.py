"""Timer, session and allocation rules, read through /api/v2/.

Most of these came from tests of the old server-rendered start/stop/update/
delete pages (core.tests, core.test_timers_desk, core.test_allocation_editor_web).
The React pages post to the endpoints below, so the behaviour is asserted here.
"""

from datetime import datetime, timedelta, timezone as datetime_timezone

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.test import APIClient

from core.models import Projects, Sessions, SubProjects, TimerReminder
from core.services import SessionMutationService
from core.totals import derived_project_totals, derived_subproject_totals

UTC = datetime_timezone.utc


def derived_project_total(user, project):
    return derived_project_totals(user, [project.pk])[project.pk]


def derived_subproject_total(user, subproject):
    return derived_subproject_totals(user, [subproject.pk])[subproject.pk]


class TimerBehaviourTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="timer-user", password="pw")
        self.project = Projects.objects.create(user=self.user, name="Focus Block")
        self.first = SubProjects.objects.create(
            user=self.user, parent_project=self.project, name="First"
        )
        self.second = SubProjects.objects.create(
            user=self.user, parent_project=self.project, name="Second"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _start(self, **extra):
        return self.client.post(
            "/api/v2/timers/", {"project_id": self.project.pk, **extra}, format="json"
        )

    def _active(self, **kwargs):
        return SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            subprojects=[self.first, self.second],
            start_time=kwargs.pop("start_time", timezone.now() - timedelta(hours=1)),
            **kwargs,
        )

    def _completed(self):
        now = timezone.now().replace(microsecond=0)
        return SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            subprojects=[self.first, self.second],
            start_time=now - timedelta(hours=1),
            end_time=now,
        )

    def _other_user(self):
        return User.objects.create_user(username="other", email="o@example.com", password="pw")


class StartTimerTests(TimerBehaviourTestCase):
    def test_stop_after_minutes_sets_auto_stop(self):
        response = self._start(stop_after_minutes=30)
        self.assertEqual(response.status_code, 201, response.content)
        session = Sessions.objects.get(user=self.user, project=self.project)
        self.assertTrue(session.is_active)
        self.assertAlmostEqual(
            (session.auto_stop_at - session.start_time).total_seconds(), 30 * 60, delta=2
        )

    def test_without_stop_after_or_reminder_there_is_neither(self):
        self.assertEqual(self._start().status_code, 201)
        session = Sessions.objects.get(user=self.user)
        self.assertIsNone(session.auto_stop_at)
        self.assertIsNone(session.end_time)
        self.assertFalse(session.notify_on_auto_stop)
        self.assertFalse(TimerReminder.objects.exists())

    def test_one_shot_reminder_and_auto_stop_notification_preference(self):
        response = self._start(
            notify_on_auto_stop=True,
            reminder={"mode": "after", "amount": 20, "unit": "minutes", "message": "Check in"},
        )
        self.assertEqual(response.status_code, 201, response.content)
        session = Sessions.objects.get(user=self.user, end_time__isnull=True)
        self.assertTrue(session.notify_on_auto_stop)
        reminder = TimerReminder.objects.get(session=session)
        self.assertEqual(reminder.mode, "after")
        self.assertIsNone(reminder.interval_seconds)
        self.assertEqual(
            int((reminder.next_fire_at - session.start_time).total_seconds()), 20 * 60
        )
        self.assertEqual(reminder.message, "Check in")

    def test_interval_reminder(self):
        self._start(reminder={"mode": "interval", "amount": 5, "unit": "minutes"})
        session = Sessions.objects.get(user=self.user, end_time__isnull=True)
        reminder = TimerReminder.objects.get(session=session)
        self.assertIsNone(session.auto_stop_at)
        self.assertEqual(reminder.mode, "interval")
        self.assertEqual(reminder.interval_seconds, 5 * 60)

    def test_at_reminder_keeps_the_instant_it_names(self):
        # The browser turns the user's wall-clock time into an offset time using
        # their profile timezone; the server stores that instant.
        response = self._start(reminder={"mode": "at", "at": "2030-08-05T15:30:00-04:00"})
        self.assertEqual(response.status_code, 201, response.content)
        reminder = TimerReminder.objects.get(session__user=self.user)
        self.assertEqual(reminder.mode, "at")
        self.assertEqual(reminder.next_fire_at.isoformat(), "2030-08-05T19:30:00+00:00")

    def test_a_past_at_reminder_is_rejected_and_no_timer_is_created(self):
        response = self._start(reminder={"mode": "at", "at": "2020-01-01T12:00:00Z"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("future", str(response.json()["error"]["details"]))
        self.assertFalse(Sessions.objects.filter(user=self.user).exists())
        self.assertFalse(TimerReminder.objects.exists())

    def test_another_users_project_cannot_be_started(self):
        foreign = Projects.objects.create(user=self._other_user(), name="Foreign")
        response = self.client.post("/api/v2/timers/", {"project_id": foreign.pk}, format="json")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Sessions.objects.filter(user=self.user).exists())

    def test_starting_a_second_timer_is_allowed(self):
        self.assertEqual(self._start().status_code, 201)
        self.assertEqual(self._start().status_code, 201)
        self.assertEqual(Sessions.objects.filter(user=self.user, end_time__isnull=True).count(), 2)


class ExpiredTimerTests(TimerBehaviourTestCase):
    def test_expired_stop_after_timer_is_closed_before_listing_active_timers(self):
        start = timezone.now() - timedelta(minutes=45)
        auto_stop_at = start + timedelta(minutes=30)
        session = Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=start,
            auto_stop_at=auto_stop_at,
            is_active=True,
        )

        response = self.client.get("/api/v2/timers/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["timers"], [])
        session.refresh_from_db()
        self.assertFalse(session.is_active)
        floored = auto_stop_at.replace(microsecond=0)
        self.assertEqual(session.end_time, floored)
        self.assertIsNone(session.auto_stop_at)
        self.assertEqual(
            derived_project_total(self.user, self.project),
            round((floored - start).total_seconds() / 60.0, 4),
        )

    def test_a_timer_that_has_not_expired_stays_running(self):
        start = timezone.now() - timedelta(minutes=5)
        session = Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=start,
            auto_stop_at=start + timedelta(minutes=30),
            is_active=True,
        )
        listed = self.client.get("/api/v2/timers/").json()["timers"]
        self.assertEqual([row["id"] for row in listed], [session.pk])


class StopTimerTests(TimerBehaviourTestCase):
    def test_stop_closes_the_timer_and_totals_follow(self):
        timer = self._active()
        response = self.client.post(f"/api/v2/timers/{timer.pk}/stop/", {}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        timer.refresh_from_db()
        self.assertFalse(timer.is_active)
        self.assertIsNotNone(timer.end_time)
        self.assertAlmostEqual(
            derived_project_total(self.user, self.project), timer.duration, places=2
        )
        for sub in (self.first, self.second):
            self.assertAlmostEqual(
                derived_subproject_total(self.user, sub), timer.duration, places=2
            )

    @freeze_time("2026-08-05 10:11:29+00:00")
    def test_stop_without_explicit_times_preserves_second_accuracy(self):
        started_at = datetime(2026, 8, 5, 9, 7, 43, tzinfo=UTC)
        timer = Sessions.objects.create(user=self.user, project=self.project, start_time=started_at)
        response = self.client.post(f"/api/v2/timers/{timer.pk}/stop/", {}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        timer.refresh_from_db()
        self.assertEqual(timer.start_time, started_at)
        self.assertEqual(timer.end_time.second, 29)
        self.assertEqual(timer.end_time.microsecond, 0)

    def test_stop_keeps_the_running_note_unless_one_is_sent(self):
        timer = self._active(note="running note")
        self.client.post(f"/api/v2/timers/{timer.pk}/stop/", {}, format="json")
        timer.refresh_from_db()
        self.assertEqual(timer.note, "running note")

    def test_stop_can_replace_the_note(self):
        timer = self._active(note="running note")
        self.client.post(f"/api/v2/timers/{timer.pk}/stop/", {"note": "final"}, format="json")
        timer.refresh_from_db()
        self.assertEqual(timer.note, "final")

    def test_explicit_allocations_are_stored(self):
        timer = self._active(note="running note")
        response = self.client.post(
            f"/api/v2/timers/{timer.pk}/stop/",
            {
                "subproject_allocations": [
                    {"subproject_id": self.first.pk, "allocation_bp": 2500},
                    {"subproject_id": self.second.pk, "allocation_bp": 7500},
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        timer.refresh_from_db()
        self.assertIsNotNone(timer.end_time)
        self.assertEqual(
            dict(timer.subproject_links.values_list("subproject_id", "allocation_bp")),
            {self.first.pk: 2500, self.second.pk: 7500},
        )

    def test_allocations_over_100_percent_are_rejected_and_the_timer_keeps_running(self):
        timer = self._active()
        response = self.client.post(
            f"/api/v2/timers/{timer.pk}/stop/",
            {
                "subproject_allocations": [
                    {"subproject_id": self.first.pk, "allocation_bp": 6000},
                    {"subproject_id": self.second.pk, "allocation_bp": 5000},
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("10000 basis points", str(response.json()["error"]["details"]))
        timer.refresh_from_db()
        self.assertIsNone(timer.end_time)

    def test_an_unallocated_shortfall_is_accepted(self):
        timer = self._active()
        response = self.client.post(
            f"/api/v2/timers/{timer.pk}/stop/",
            {
                "subproject_allocations": [
                    {"subproject_id": self.first.pk, "allocation_bp": 5000},
                    {"subproject_id": self.second.pk, "allocation_bp": 4000},
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            sum(timer.subproject_links.values_list("allocation_bp", flat=True)), 9000
        )


class TimerNoteTests(TimerBehaviourTestCase):
    def test_active_note_persists_and_completed_timers_conflict(self):
        timer = SessionMutationService.create_session(user=self.user, project=self.project)
        response = self.client.patch(
            f"/api/v2/timers/{timer.pk}", {"note": "checkpoint"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        timer.refresh_from_db()
        self.assertEqual(timer.note, "checkpoint")

        SessionMutationService.mutate_session(timer.pk, user=self.user, end_time=timezone.now())
        late = self.client.patch(f"/api/v2/timers/{timer.pk}", {"note": "late"}, format="json")
        self.assertEqual(late.status_code, 409)

    def test_notes_enforce_ownership(self):
        other = self._other_user()
        foreign = SessionMutationService.create_session(
            user=other, project=Projects.objects.create(user=other, name="Other")
        )
        response = self.client.patch(
            f"/api/v2/timers/{foreign.pk}", {"note": "nope"}, format="json"
        )
        self.assertEqual(response.status_code, 404)

    def test_a_reminder_cannot_be_cancelled_by_another_account(self):
        other = self._other_user()
        foreign = SessionMutationService.create_session(
            user=other, project=Projects.objects.create(user=other, name="Other")
        )
        reminder = TimerReminder.objects.create(
            session=foreign, mode="at", next_fire_at=timezone.now() + timedelta(minutes=5)
        )
        response = self.client.delete(f"/api/v2/timers/{foreign.pk}/reminders/{reminder.pk}")
        self.assertEqual(response.status_code, 204)  # idempotent delete: nothing of yours to remove
        reminder.refresh_from_db()
        self.assertTrue(reminder.active)


class SessionEditTests(TimerBehaviourTestCase):
    def test_editing_a_session_moves_its_time_between_subprojects(self):
        session = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=timezone.now() - timedelta(hours=2),
            end_time=timezone.now() - timedelta(hours=1),
            is_active=False,
            subprojects=[self.first],
        )
        self.assertAlmostEqual(derived_project_total(self.user, self.project), 60.0, places=2)
        self.assertAlmostEqual(derived_subproject_total(self.user, self.first), 60.0, places=2)
        self.assertAlmostEqual(derived_subproject_total(self.user, self.second), 0.0, places=2)

        start = (timezone.now() - timedelta(hours=3)).replace(microsecond=0)
        response = self.client.patch(
            f"/api/v2/sessions/{session.pk}",
            {
                "start": start.isoformat(),
                "end": (start + timedelta(minutes=90)).isoformat(),
                "note": "Updated session",
                "subproject_ids": [self.second.pk],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Sessions.objects.filter(user=self.user).count(), 1)
        session.refresh_from_db()
        self.assertEqual(session.note, "Updated session")
        self.assertAlmostEqual(derived_project_total(self.user, self.project), 90.0, places=2)
        self.assertAlmostEqual(derived_subproject_total(self.user, self.first), 0.0, places=2)
        self.assertAlmostEqual(derived_subproject_total(self.user, self.second), 90.0, places=2)

    def test_a_note_only_edit_leaves_totals_alone(self):
        session = self._completed()
        self.client.patch(
            f"/api/v2/sessions/{session.pk}", {"note": "only the note"}, format="json"
        )
        self.assertAlmostEqual(derived_project_total(self.user, self.project), 60.0, places=2)
        self.assertAlmostEqual(derived_subproject_total(self.user, self.first), 60.0, places=2)

    def test_explicit_allocations_on_edit(self):
        session = self._completed()
        response = self.client.patch(
            f"/api/v2/sessions/{session.pk}",
            {
                "subproject_allocations": [
                    {"subproject_id": self.first.pk, "allocation_bp": 3000},
                    {"subproject_id": self.second.pk, "allocation_bp": 7000},
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            dict(session.subproject_links.values_list("subproject_id", "allocation_bp")),
            {self.first.pk: 3000, self.second.pk: 7000},
        )

    def test_allocations_over_100_percent_are_rejected_and_nothing_changes(self):
        session = self._completed()
        response = self.client.patch(
            f"/api/v2/sessions/{session.pk}",
            {
                "note": "edited",
                "subproject_allocations": [
                    {"subproject_id": self.first.pk, "allocation_bp": 6000},
                    {"subproject_id": self.second.pk, "allocation_bp": 5000},
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("10000 basis points", str(response.json()["error"]["details"]))
        session.refresh_from_db()
        self.assertNotEqual(session.note, "edited")
        self.assertEqual(
            set(session.subproject_links.values_list("allocation_bp", flat=True)), {5000}
        )

    def test_an_unallocated_shortfall_is_accepted_on_edit(self):
        session = self._completed()
        response = self.client.patch(
            f"/api/v2/sessions/{session.pk}",
            {
                "subproject_allocations": [
                    {"subproject_id": self.first.pk, "allocation_bp": 5000},
                    {"subproject_id": self.second.pk, "allocation_bp": 4000},
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            sum(session.subproject_links.values_list("allocation_bp", flat=True)), 9000
        )

    def test_edits_keep_second_accuracy(self):
        session = self._completed()
        response = self.client.patch(
            f"/api/v2/sessions/{session.pk}",
            {"start": "2026-08-05T09:07:43Z", "end": "2026-08-05T10:11:29Z"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        session.refresh_from_db()
        self.assertEqual(session.start_time, datetime(2026, 8, 5, 9, 7, 43, tzinfo=UTC))
        self.assertEqual(session.end_time, datetime(2026, 8, 5, 10, 11, 29, tzinfo=UTC))

    def test_a_session_is_found_by_uuid(self):
        # The uuid survives export/re-import, so /update_session/<uuid>/ is a
        # stable external link; the React page resolves it with ?uuid=.
        session = self._completed()
        response = self.client.get("/api/v2/sessions/", {"uuid": str(session.uuid)})
        self.assertEqual([row["id"] for row in response.json()["sessions"]], [session.pk])
        self.assertEqual(response.json()["sessions"][0]["project"]["name"], self.project.name)

    def test_delete_session_removes_it_and_its_totals(self):
        session = self._completed()
        self.assertAlmostEqual(derived_project_total(self.user, self.project), 60.0, places=2)
        response = self.client.delete(f"/api/v2/sessions/{session.pk}")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Sessions.objects.filter(pk=session.pk).exists())
        self.assertAlmostEqual(derived_project_total(self.user, self.project), 0.0, places=2)
        for sub in (self.first, self.second):
            self.assertAlmostEqual(derived_subproject_total(self.user, sub), 0.0, places=2)
