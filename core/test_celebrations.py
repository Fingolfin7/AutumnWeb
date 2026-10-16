"""Focused contracts for milestone detection and its user-visible markup."""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient
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


class CelebrationApiTests(TestCase):
    """The celebration the React app toasts, from the API responses that carry it."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="celebrant", email="celebrant@example.com", password="pw"
        )
        self.context = Context.objects.create(user=self.user, name="Work")
        self.project = Projects.objects.create(
            user=self.user, name="Atlas API", context=self.context
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _patch_project(self, **body):
        return self.client.patch(
            f"/api/v2/projects/{self.project.pk}", body, format="json"
        )

    def test_marking_a_project_complete_carries_a_completion_celebration(self):
        response = self._patch_project(status="complete")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["celebration"]["kind"], "completion")
        self.assertIn("Project complete", response.json()["celebration"]["message"])


    def test_saving_an_already_complete_project_does_not_replay_celebration(self):
        first = self._patch_project(status="complete")
        second = self._patch_project(status="complete", description="touch")
        self.assertEqual(first.json()["celebration"]["kind"], "completion")
        self.assertNotIn("celebration", second.json())


    def test_stopping_at_a_tracked_time_threshold_carries_a_progress_celebration(self):
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
            user=self.user, project=self.project, start_time=now - timedelta(hours=2), is_active=True
        )
        response = self.client.post(f"/api/v2/timers/{timer.pk}/stop/", {}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["celebration"]["kind"], "progress")
        self.assertIn("10h tracked", response.json()["celebration"]["message"])

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
            user=self.user, project=self.project, start_time=now - timedelta(hours=1), is_active=True
        )
        response = self.client.post(f"/api/v2/timers/{timer.pk}/stop/", {}, format="json")
        self.assertEqual(response.json()["celebration"]["kind"], "progress")
        self.assertIn("commitment met: Atlas API", response.json()["celebration"]["message"])
