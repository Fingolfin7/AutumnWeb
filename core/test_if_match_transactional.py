"""Optimistic-concurrency (If-Match) checks run under the row lock.

Finding 2: the pre-lock version comparison was a TOCTOU race. These tests pin
the comparison to the freshly-locked row inside the mutation services and to the
409 conflict envelope the v2 endpoints return.
"""

from datetime import datetime, timedelta, timezone as datetime_timezone

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import Projects, SubProjects
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
