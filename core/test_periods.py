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


