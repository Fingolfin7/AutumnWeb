"""Optimistic-concurrency (If-Match) checks run under the row lock.

Finding 2: the pre-lock version comparison was a TOCTOU race. These tests pin
the comparison to the freshly-locked row inside the mutation services and to the
409 conflict envelope the v2 endpoints return.
"""

from datetime import datetime, timedelta, timezone as datetime_timezone

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from freezegun import freeze_time
from rest_framework.test import APIClient

from core.models import Commitment, Projects, SubProjects
from core.services import SessionMutationService, StaleVersionError


UTC = datetime_timezone.utc


class SessionServiceIfMatchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ifmatch-svc")
        self.project = Projects.objects.create(user=self.user, name="Focus")
        self.start = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)

    def _completed_session(self):
        return SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=self.start,
            end_time=self.start + timedelta(minutes=30),
            is_active=False,
        )

    def test_matching_expected_version_succeeds_and_bumps(self):
        session = self._completed_session()
        self.assertEqual(session.version, 1)

        updated = SessionMutationService.mutate_session(
            session.pk,
            user=self.user,
            note="edited",
            expected_version=1,
        )
        self.assertEqual(updated.version, 2)
        self.assertEqual(updated.note, "edited")

    def test_stale_expected_version_raises_with_fresh_current(self):
        session = self._completed_session()

        with self.assertRaises(StaleVersionError) as ctx:
            SessionMutationService.mutate_session(
                session.pk,
                user=self.user,
                note="never applied",
                expected_version=99,
            )
        self.assertEqual(ctx.exception.current.version, 1)
        # The mutation must not have applied.
        session.refresh_from_db()
        self.assertEqual(session.version, 1)
        self.assertIsNone(session.note)

    def test_delete_session_honors_expected_version(self):
        session = self._completed_session()

        with self.assertRaises(StaleVersionError) as ctx:
            SessionMutationService.delete_session(
                session.pk, user=self.user, expected_version=99
            )
        self.assertEqual(ctx.exception.current.version, 1)
        # The stale delete must have been rejected before the row was removed.
        self.assertTrue(session.__class__.objects.filter(pk=session.pk).exists())
        self.assertEqual(
            SessionMutationService.delete_session(
                session.pk, user=self.user, expected_version=1
            ),
            session.pk,
        )

    def test_race_comparison_uses_locked_row_not_stale_read(self):
        """Sequential simulation of two writers holding the same stale read.

        The first writer bumps the version; the second replays the OLD version it
        captured before that write. Because the comparison happens against the
        freshly-locked row (not the caller's stale view), the second write must
        be rejected.
        """
        session = self._completed_session()
        stale_version = session.version  # both "writers" observed version 1

        first = SessionMutationService.mutate_session(
            session.pk,
            user=self.user,
            note="first writer wins",
            expected_version=stale_version,
        )
        self.assertEqual(first.version, stale_version + 1)

        with self.assertRaises(StaleVersionError) as ctx:
            SessionMutationService.mutate_session(
                session.pk,
                user=self.user,
                note="second writer loses",
                expected_version=stale_version,
            )
        self.assertEqual(ctx.exception.current.version, stale_version + 1)
        session.refresh_from_db()
        self.assertEqual(session.note, "first writer wins")


class SessionEndpointIfMatchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ifmatch-session-ep")
        self.project = Projects.objects.create(user=self.user, name="Focus")
        self.subproject = SubProjects.objects.create(
            user=self.user, parent_project=self.project, name="Alpha"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.session = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=datetime(2026, 7, 16, 9, 0, tzinfo=UTC),
            end_time=datetime(2026, 7, 16, 9, 30, tzinfo=UTC),
            is_active=False,
        )

    def test_stale_if_match_returns_version_conflict(self):
        url = reverse("api_v2:session-detail", args=[self.session.id])
        # Advance the version once so the next write with the original tag is stale.
        ok = self.client.patch(
            url, {"note": "first"}, format="json", HTTP_IF_MATCH="1"
        )
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(ok.json()["version"], 2)

        stale = self.client.patch(
            url, {"note": "stale"}, format="json", HTTP_IF_MATCH="1"
        )
        self.assertEqual(stale.status_code, 409)
        body = stale.json()
        self.assertEqual(body["error"]["code"], "version_conflict")
        self.assertEqual(body["error"]["details"]["current"]["version"], 2)
        self.assertEqual(body["error"]["details"]["current"]["note"], "first")

    def test_correct_if_match_succeeds(self):
        url = reverse("api_v2:session-detail", args=[self.session.id])
        response = self.client.patch(
            url, {"note": "applied"}, format="json", HTTP_IF_MATCH="1"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["version"], 2)
        self.assertEqual(response.json()["note"], "applied")


class CommitmentEndpointIfMatchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ifmatch-commitment-ep")
        self.project = Projects.objects.create(user=self.user, name="Focus")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _create_commitment(self):
        response = self.client.post(
            reverse("api_v2:commitments"),
            {
                "aggregation_type": "project",
                "project_id": self.project.pk,
                "commitment_type": "time",
                "period": "daily",
                "start_date": "2026-01-01",
                "timezone": "Europe/Prague",
                "target_value": 60,
                "banking_enabled": True,
                "max_balance": 600,
                "min_balance": -600,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    @freeze_time("2026-01-01 12:00:00+00:00")
    def test_stale_then_correct_if_match(self):
        commitment = self._create_commitment()
        url = reverse("api_v2:commitment-detail", args=[commitment["id"]])
        self.assertEqual(commitment["version"], 1)

        ok = self.client.patch(
            url, {"max_balance": 700}, format="json", HTTP_IF_MATCH="1"
        )
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(ok.json()["version"], 2)

        stale = self.client.patch(
            url, {"max_balance": 500}, format="json", HTTP_IF_MATCH="1"
        )
        self.assertEqual(stale.status_code, 409)
        body = stale.json()
        self.assertEqual(body["error"]["code"], "version_conflict")
        self.assertEqual(body["error"]["details"]["current"]["version"], 2)

        correct = self.client.patch(
            url, {"max_balance": 500}, format="json", HTTP_IF_MATCH="2"
        )
        self.assertEqual(correct.status_code, 200, correct.content)
        self.assertEqual(correct.json()["version"], 3)
