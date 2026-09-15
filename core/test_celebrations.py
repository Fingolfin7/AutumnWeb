"""Focused contracts for milestone detection and its user-visible markup."""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.celebrations import (
    crossed_tracked_time_milestone,
    is_completion_transition,
)
from core.models import Commitment, Context, Projects
from core.services import SessionMutationService


class CelebrationDecisionTests(TestCase):
    def test_completion_requires_a_live_to_complete_transition(self):
        self.assertTrue(is_completion_transition("active", "complete"))
        self.assertTrue(is_completion_transition("paused", "complete"))
        self.assertFalse(is_completion_transition("complete", "complete"))
        self.assertFalse(is_completion_transition("complete", "active"))
        self.assertFalse(is_completion_transition("active", "paused"))

    def test_tracked_time_threshold_uses_a_strict_before_boundary(self):
        self.assertEqual(crossed_tracked_time_milestone(599, 600), 600)
        self.assertIsNone(crossed_tracked_time_milestone(600, 601))
        self.assertEqual(crossed_tracked_time_milestone(0, 1600), 1500)


class CelebrationMarkupTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="celebrant", email="celebrant@example.com", password="pw"
        )
        self.context = Context.objects.create(user=self.user, name="Work")
        self.project = Projects.objects.create(
            user=self.user, name="Atlas API", context=self.context
        )
        self.client.login(username="celebrant", password="pw")

    def test_marking_a_project_complete_renders_the_completion_contract(self):
        response = self.client.post(
            reverse("update_project", args=[self.project.pk]),
            {
                "name": self.project.name,
                "status": "complete",
                "description": "",
                "context": str(self.context.pk),
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-celebration="completion"')
        self.assertContains(response, "Project complete")
        self.assertContains(response, "data-celebration-leaf=")

    def test_a_normal_project_edit_stays_quiet(self):
        response = self.client.post(
            reverse("update_project", args=[self.project.pk]),
            {
                "name": "Atlas API, revised",
                "status": "active",
                "description": "",
                "context": str(self.context.pk),
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "data-celebration=")
        self.assertContains(response, "Project updated successfully")

    def test_saving_an_already_complete_project_does_not_replay_celebration(self):
        payload = {
            "name": self.project.name,
            "status": "complete",
            "description": "",
            "context": str(self.context.pk),
        }
        first_response = self.client.post(
            reverse("update_project", args=[self.project.pk]), payload, follow=True
        )
        second_response = self.client.post(
            reverse("update_project", args=[self.project.pk]), payload, follow=True
        )

        self.assertContains(first_response, 'data-celebration="completion"')
        self.assertNotContains(second_response, "data-celebration=")
        self.assertContains(second_response, "Project updated successfully")

    def test_completing_a_project_without_history_uses_a_direct_copy(self):
        response = self.client.post(
            reverse("update_project", args=[self.project.pk]),
            {
                "name": self.project.name,
                "status": "complete",
                "description": "",
                "context": str(self.context.pk),
            },
            follow=True,
        )

        self.assertContains(response, "Project complete — no sessions logged yet.")
        self.assertNotContains(response, "0m across 0 sessions")

    def test_stopping_at_a_tracked_time_threshold_renders_progress_contract(self):
        now = timezone.now().replace(microsecond=0)
        for index in range(9):
            SessionMutationService.create_session(
                user=self.user,
                project=self.project,
                start_time=now - timedelta(days=index + 1, hours=1),
                end_time=now - timedelta(days=index + 1),
                is_active=False,
            )
        timer = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=now - timedelta(hours=2),
            is_active=True,
        )

        response = self.client.post(
            reverse("stop_timer", args=[timer.pk]),
            {},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-celebration="progress"')
        self.assertContains(response, "10h tracked")

    def test_stopping_when_a_current_commitment_first_reaches_100_percent(self):
        Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type="time",
            period="weekly",
            target=60,
        )
        now = timezone.now().replace(microsecond=0)
        timer = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=now - timedelta(hours=1),
            is_active=True,
        )

        response = self.client.post(
            reverse("stop_timer", args=[timer.pk]),
            {},
            follow=True,
        )

        self.assertContains(response, 'data-celebration="progress"')
        self.assertContains(response, "commitment met: Atlas API")
