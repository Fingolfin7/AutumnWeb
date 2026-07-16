"""Tests for client-supplied instants on v1 timer start/stop.

CLI clients on sleeping hosts send the instant the user ran the command so a
wake delay never skews recorded times.
"""

from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time

from core.models import Projects, Sessions

FROZEN = "2026-07-16 12:00:00+00:00"


@freeze_time(FROZEN)
class TimerClientInstantTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="instants")
        self.client.force_login(self.user)
        self.project = Projects.objects.create(user=self.user, name="Clock")

    def _start(self, **extra):
        return self.client.post(
            "/api/timer/start/",
            data={"project": "Clock", **extra},
            content_type="application/json",
        )

    def _stop(self, **extra):
        return self.client.post(
            "/api/timer/stop/",
            data=extra,
            content_type="application/json",
        )

    def test_start_uses_client_instant(self):
        client_start = datetime(2026, 7, 16, 11, 58, 30, tzinfo=dt_timezone.utc)
        response = self._start(start=client_start.isoformat())
        self.assertEqual(response.status_code, 201)
        sess = Sessions.objects.get(pk=response.json()["session"]["id"])
        self.assertEqual(sess.start_time, client_start)

    def test_start_without_instant_uses_server_now(self):
        response = self._start()
        self.assertEqual(response.status_code, 201)
        sess = Sessions.objects.get(pk=response.json()["session"]["id"])
        self.assertEqual(sess.start_time, timezone.now())

    def test_start_rejects_far_future_instant(self):
        future = timezone.now() + timedelta(minutes=10)
        response = self._start(start=future.isoformat())
        self.assertEqual(response.status_code, 400)
        self.assertIn("future", response.json()["error"])

    def test_start_rejects_garbage_instant(self):
        response = self._start(start="not-a-time")
        self.assertEqual(response.status_code, 400)

    def test_auto_stop_derived_from_client_start(self):
        client_start = datetime(2026, 7, 16, 11, 30, 0, tzinfo=dt_timezone.utc)
        response = self._start(start=client_start.isoformat(), stop_after="45m")
        self.assertEqual(response.status_code, 201)
        sess = Sessions.objects.get(pk=response.json()["session"]["id"])
        self.assertEqual(sess.auto_stop_at, client_start + timedelta(minutes=45))

    def test_stop_uses_client_instant(self):
        started = self._start(start="2026-07-16T11:00:00+00:00")
        session_id = started.json()["session"]["id"]
        client_end = datetime(2026, 7, 16, 11, 59, 0, tzinfo=dt_timezone.utc)
        response = self._stop(session_id=session_id, end=client_end.isoformat())
        self.assertEqual(response.status_code, 200)
        sess = Sessions.objects.get(pk=session_id)
        self.assertEqual(sess.end_time, client_end)
        self.assertFalse(sess.is_active)

    def test_stop_rejects_end_before_start(self):
        started = self._start(start="2026-07-16T11:00:00+00:00")
        session_id = started.json()["session"]["id"]
        response = self._stop(
            session_id=session_id, end="2026-07-16T10:59:00+00:00"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("before the session start", response.json()["error"])
        self.assertTrue(Sessions.objects.get(pk=session_id).is_active)

    def test_stop_rejects_far_future_instant(self):
        started = self._start()
        session_id = started.json()["session"]["id"]
        future = timezone.now() + timedelta(minutes=10)
        response = self._stop(session_id=session_id, end=future.isoformat())
        self.assertEqual(response.status_code, 400)
