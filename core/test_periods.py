from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model

from core.models import Projects, Sessions


class LogPeriodSemanticsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="u", password="p")
        self.project = Projects.objects.create(user=self.user, name="P")

    def _create_session_ended(self, minutes_ago: int):
        end = timezone.now() - timedelta(minutes=minutes_ago)
        start = end - timedelta(minutes=10)
        return Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=start,
            end_time=end,
            is_active=False,
        )

    def test_week_is_trailing_7_days(self):
        # 2 days ago should be included
        self._create_session_ended(minutes_ago=2 * 24 * 60)

        self.client.force_login(self.user)
        resp = self.client.get("/api/log/?period=week&compact=true")
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertGreaterEqual(payload.get("count", 0), 1)

    def test_week_excludes_older_than_7_days(self):
        # 8 days ago should be excluded
        self._create_session_ended(minutes_ago=8 * 24 * 60)

        self.client.force_login(self.user)
        resp = self.client.get("/api/log/?period=week&compact=true")
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload.get("count", 0), 0)
