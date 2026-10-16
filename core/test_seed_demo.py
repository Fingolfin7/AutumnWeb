from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils.crypto import get_random_string

from core.models import Commitment, Context, Projects, Sessions, Tag


def seed(*args, **kwargs):
    out = StringIO()
    call_command("seed_demo", *args, stdout=out, **kwargs)
    return out.getvalue()


@override_settings(DEBUG=True)
class SeedDemoTests(TestCase):
    def test_creates_fictional_account(self):
        seed()
        user = User.objects.get(username="demo")
        self.assertTrue(user.check_password("demo-pass-123"))
        self.assertFalse(user.profile.ai_features_enabled)
        self.assertEqual(Context.objects.filter(user=user).count(), 3)
        self.assertGreaterEqual(Tag.objects.filter(user=user).count(), 3)
        statuses = set(Projects.objects.filter(user=user).values_list("status", flat=True))
        self.assertTrue({"active", "paused", "complete"} <= statuses)
        sessions = Sessions.objects.filter(user=user)
        self.assertGreater(sessions.count(), 20)
        self.assertFalse(sessions.filter(end_time__isnull=True).exists())
        self.assertTrue(sessions.filter(note__icontains="grammar").exists())
        self.assertEqual(Commitment.objects.filter(user=user).count(), 1)

    def test_is_deterministic_and_reset_recreates(self):
        seed("--username=demo-a", f"--password={get_random_string(12)}")
        first = sorted(
            Sessions.objects.filter(user__username="demo-a").values_list("note", "project__name")
        )
        seed("--username=demo-a", "--reset")
        second = sorted(
            Sessions.objects.filter(user__username="demo-a").values_list("note", "project__name")
        )
        self.assertEqual(first, second)
        self.assertEqual(User.objects.filter(username="demo-a").count(), 1)
        self.assertTrue(User.objects.get(username="demo-a").check_password("demo-pass-123"))


    def test_reset_refused_without_debug_unless_forced(self):
        seed()
        with override_settings(DEBUG=False):
            with self.assertRaises(CommandError):
                seed("--reset")
            self.assertTrue(User.objects.filter(username="demo").exists())
            seed("--reset", "--force")
        self.assertTrue(User.objects.filter(username="demo").exists())
