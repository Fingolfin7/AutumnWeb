"""The header context switcher, and the running badge on project rows.

Both cover things that failed silently before: the set-context endpoint raised
TypeError on every POST because the view shadowed the helper it called, and the
project rows gave no sign that their one-tap start button was about to open a
second concurrent timer.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Context, Projects, Sessions


class ContextSwitchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="switcher", email="s@example.com", password="pw"
        )
        cls.work = Context.objects.create(user=cls.user, name="Work")
        cls.study = Context.objects.create(user=cls.user, name="Study")
        cls.other = User.objects.create_user(
            username="stranger", email="x@example.com", password="pw"
        )
        cls.theirs = Context.objects.create(user=cls.other, name="Theirs")

    def setUp(self):
        self.client.login(username="switcher", password="pw")

    def test_posting_a_context_makes_it_active(self):
        """This is the regression: the view was named the same as the helper
        it calls, so `from core.utils import *` was shadowed and every POST
        raised TypeError. Nothing linked to it, so nobody found out."""
        response = self.client.post(
            reverse("set_active_context"), {"context_id": self.work.id, "next": "/"}
        )
        self.assertEqual(response.status_code, 302)
        body = self.client.get(reverse("home")).content.decode()
        self.assertIn(f'<option value="{self.work.id}" selected>', body)

    def test_all_clears_the_selection(self):
        self.client.post(reverse("set_active_context"), {"context_id": self.work.id})
        self.client.post(reverse("set_active_context"), {"context_id": "all"})
        body = self.client.get(reverse("home")).content.decode()
        self.assertIn('<option value="all" selected>', body)

    def test_another_users_context_is_ignored(self):
        self.client.post(
            reverse("set_active_context"), {"context_id": self.theirs.id}
        )
        body = self.client.get(reverse("home")).content.decode()
        self.assertIn('<option value="all" selected>', body)
        self.assertNotIn("Theirs", body)

    def test_garbage_falls_back_to_all(self):
        for value in ("not-a-number", "", "99999"):
            with self.subTest(value=value):
                response = self.client.post(
                    reverse("set_active_context"), {"context_id": value}
                )
                self.assertEqual(response.status_code, 302)

    def test_does_not_redirect_off_site(self):
        response = self.client.post(
            reverse("set_active_context"),
            {"context_id": "all", "next": "https://example.com/phish"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("home"))

    def test_switcher_renders_when_the_user_has_contexts(self):
        body = self.client.get(reverse("home")).content.decode()
        self.assertIn('id="context-switch"', body)
        self.assertIn("All contexts", body)
        self.assertIn("Work", body)

    def test_switcher_is_hidden_when_there_are_no_contexts(self):
        """With nothing to switch between it could only say "All contexts"."""
        Context.objects.filter(user=self.user).delete()
        body = self.client.get(reverse("home")).content.decode()
        self.assertNotIn('id="context-switch"', body)


class ProjectRunningBadgeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="runner", email="r@example.com", password="pw"
        )
        cls.busy = Projects.objects.create(user=cls.user, name="Atlas API")
        cls.idle = Projects.objects.create(user=cls.user, name="Quiet Thing")

    def setUp(self):
        self.client.login(username="runner", password="pw")

    def test_no_badge_when_nothing_is_running(self):
        body = self.client.get(reverse("projects")).content.decode()
        self.assertNotIn("project-running", body)

    def test_badge_marks_only_the_project_with_an_open_session(self):
        Sessions.objects.create(
            user=self.user,
            project=self.busy,
            start_time=timezone.now() - timedelta(minutes=10),
        )
        body = self.client.get(reverse("projects")).content.decode()
        self.assertEqual(body.count("project-running"), 1)
        self.assertIn("project-start is-running", body)
        # and the start button says what it will actually do
        self.assertIn("Start ANOTHER timer on Atlas API", body)

    def test_a_finished_session_does_not_count_as_running(self):
        end = timezone.now() - timedelta(minutes=5)
        Sessions.objects.create(
            user=self.user,
            project=self.busy,
            start_time=end - timedelta(minutes=30),
            end_time=end,
        )
        body = self.client.get(reverse("projects")).content.decode()
        self.assertNotIn("project-running", body)

    def test_another_users_running_timer_does_not_leak(self):
        stranger = User.objects.create_user(
            username="nosy", email="n@example.com", password="pw"
        )
        theirs = Projects.objects.create(user=stranger, name="Atlas API")
        Sessions.objects.create(
            user=stranger, project=theirs, start_time=timezone.now()
        )
        body = self.client.get(reverse("projects")).content.decode()
        self.assertNotIn("project-running", body)

    def test_starting_a_second_timer_is_still_allowed(self):
        """Deliberate: two sessions can cover different subprojects. The badge
        is there to make it visible, not to prevent it."""
        Sessions.objects.create(
            user=self.user, project=self.busy, start_time=timezone.now()
        )
        self.client.post(reverse("start_timer"), {"project": self.busy.name})
        self.assertEqual(
            Sessions.objects.filter(
                user=self.user, project=self.busy, end_time__isnull=True
            ).count(),
            2,
        )
