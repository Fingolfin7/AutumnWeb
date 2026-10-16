"""Switching the active context.

The React header stores the choice with PATCH /api/v2/me/preferences/
(active_context_id; null means "all contexts"); the server-rendered
recommendation usage page still has the old POST /set-context/ form. List and
report endpoints never apply the stored context on their own: a client passes
it explicitly (see core.test_api_v2_web).
"""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import Context, Projects, Sessions


class ContextSwitchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="switcher", email="s@example.com", password="pw"
        )

    def setUp(self):
        self.client.login(username="switcher", password="pw")

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


class ContextPreferenceApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="switcher", email="s@example.com", password="pw"
        )
        cls.work = Context.objects.create(user=cls.user, name="Work")
        cls.other = User.objects.create_user(
            username="stranger", email="x@example.com", password="pw"
        )
        cls.theirs = Context.objects.create(user=cls.other, name="Theirs")
        cls.work_project = Projects.objects.create(user=cls.user, name="Atlas", context=cls.work)
        cls.free_project = Projects.objects.create(user=cls.user, name="Loose")

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _set(self, context_id):
        return self.client.patch(
            "/api/v2/me/preferences/", {"active_context_id": context_id}, format="json"
        )

    def test_a_context_becomes_active_and_is_remembered(self):
        response = self._set(self.work.id)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["active_context_id"], self.work.id)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.active_context_id, self.work.id)
        self.assertEqual(self.client.get("/api/v2/me/preferences/").json()["active_context_id"], self.work.id)


    def test_another_users_context_is_refused_and_nothing_changes(self):
        self._set(self.work.id)
        response = self._set(self.theirs.id)
        self.assertEqual(response.status_code, 400)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.active_context_id, self.work.id)


    def test_the_stored_context_does_not_scope_the_api_on_its_own(self):
        Sessions.objects.create(user=self.user, project=self.work_project, start_time=self._now())
        Sessions.objects.create(user=self.user, project=self.free_project, start_time=self._now())
        self._set(self.work.id)
        self.assertEqual(len(self.client.get("/api/v2/timers/").json()["timers"]), 2)
        scoped = self.client.get("/api/v2/timers/", {"context": self.work.id}).json()["timers"]
        self.assertEqual([row["project"]["name"] for row in scoped], ["Atlas"])

    @staticmethod
    def _now():
        from django.utils import timezone

        return timezone.now()
