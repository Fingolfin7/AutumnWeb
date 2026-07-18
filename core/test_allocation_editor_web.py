from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Projects, Sessions, SubProjects
from core.services import SessionMutationService


class AllocationFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="allocation-web", password="pw")
        self.client.login(username="allocation-web", password="pw")
        self.project = Projects.objects.create(user=self.user, name="Project")
        self.first = SubProjects.objects.create(
            user=self.user, parent_project=self.project, name="First"
        )
        self.second = SubProjects.objects.create(
            user=self.user, parent_project=self.project, name="Second"
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

    def _update_data(self, session, first_bp, second_bp):
        return {
            "project_name": self.project.name,
            "start_time": timezone.localtime(session.start_time).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "end_time": timezone.localtime(session.end_time).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "note": "edited",
            "subprojects": [self.first.name, self.second.name],
            f"alloc_bp_{self.first.pk}": str(first_bp),
            f"alloc_bp_{self.second.pk}": str(second_bp),
        }

    def test_update_session_accepts_explicit_allocations(self):
        session = self._completed()
        response = self.client.post(
            reverse("update_session", args=[session.pk]),
            self._update_data(session, 3000, 7000),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            dict(session.subproject_links.values_list("subproject_id", "allocation_bp")),
            {self.first.pk: 3000, self.second.pk: 7000},
        )

    def test_update_session_rejects_total_over_100_percent(self):
        session = self._completed()
        response = self.client.post(
            reverse("update_session", args=[session.pk]),
            self._update_data(session, 6000, 5000),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "must not total more than 100%")
        self.assertEqual(
            set(session.subproject_links.values_list("allocation_bp", flat=True)),
            {5000},
        )

    def test_update_session_accepts_unallocated_shortfall(self):
        session = self._completed()
        response = self.client.post(
            reverse("update_session", args=[session.pk]),
            self._update_data(session, 5000, 4000),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            sum(session.subproject_links.values_list("allocation_bp", flat=True)),
            9000,
        )

    def _active(self):
        return SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            subprojects=[self.first, self.second],
            start_time=timezone.now() - timedelta(hours=1),
            note="running note",
        )

    def test_stop_timer_accepts_explicit_allocations_and_preserves_note_initial(self):
        timer = self._active()
        page = self.client.get(reverse("stop_timer", args=[timer.pk]))
        self.assertContains(page, "running note")
        response = self.client.post(
            reverse("stop_timer", args=[timer.pk]),
            {
                "note": "running note",
                f"alloc_bp_{self.first.pk}": "2500",
                f"alloc_bp_{self.second.pk}": "7500",
            },
        )
        self.assertEqual(response.status_code, 302)
        timer.refresh_from_db()
        self.assertIsNotNone(timer.end_time)
        self.assertEqual(
            dict(timer.subproject_links.values_list("subproject_id", "allocation_bp")),
            {self.first.pk: 2500, self.second.pk: 7500},
        )

    def test_stop_timer_rejects_total_over_100_percent(self):
        timer = self._active()
        response = self.client.post(
            reverse("stop_timer", args=[timer.pk]),
            {
                f"alloc_bp_{self.first.pk}": "6000",
                f"alloc_bp_{self.second.pk}": "5000",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "must not total more than 100%")
        timer.refresh_from_db()
        self.assertIsNone(timer.end_time)

    def test_stop_timer_accepts_unallocated_shortfall(self):
        timer = self._active()
        response = self.client.post(
            reverse("stop_timer", args=[timer.pk]),
            {
                f"alloc_bp_{self.first.pk}": "5000",
                f"alloc_bp_{self.second.pk}": "4000",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            sum(timer.subproject_links.values_list("allocation_bp", flat=True)),
            9000,
        )


class TimerNoteWebTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="note-web", email="note-web@example.com", password="pw"
        )
        self.other = User.objects.create_user(
            username="note-other", email="note-other@example.com", password="pw"
        )
        self.project = Projects.objects.create(user=self.user, name="Project")
        self.other_project = Projects.objects.create(user=self.other, name="Other")
        self.client.login(username="note-web", password="pw")

    def test_active_note_endpoint_persists_and_completed_conflicts(self):
        timer = SessionMutationService.create_session(
            user=self.user, project=self.project
        )
        response = self.client.post(
            reverse("update_timer_note", args=[timer.pk]), {"note": "checkpoint"}
        )
        self.assertEqual(response.status_code, 200)
        timer.refresh_from_db()
        self.assertEqual(timer.note, "checkpoint")

        SessionMutationService.mutate_session(
            timer.pk, user=self.user, end_time=timezone.now()
        )
        response = self.client.post(
            reverse("update_timer_note", args=[timer.pk]), {"note": "late"}
        )
        self.assertEqual(response.status_code, 409)

    def test_note_endpoint_enforces_ownership(self):
        timer = SessionMutationService.create_session(
            user=self.other, project=self.other_project
        )
        response = self.client.post(
            reverse("update_timer_note", args=[timer.pk]), {"note": "nope"}
        )
        self.assertEqual(response.status_code, 404)

    def test_timers_page_contains_inline_note_editor(self):
        timer = SessionMutationService.create_session(
            user=self.user, project=self.project, note="live draft"
        )
        response = self.client.get(reverse("timers"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-timer-note-editor")
        self.assertContains(response, reverse("update_timer_note", args=[timer.pk]))
        self.assertContains(response, "live draft")
