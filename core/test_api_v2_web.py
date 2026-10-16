from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.models import Context, Projects, Sessions


class ApiV2WebTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="web-api", email="web-api@example.test", password="secret"
        )
        self.other = User.objects.create_user(
            username="other-api", email="other-api@example.test", password="secret"
        )
        self.work = Context.objects.create(user=self.user, name="Work")
        self.personal = Context.objects.create(user=self.user, name="Personal")
        self.other_context = Context.objects.create(user=self.other, name="Other")
        self.work_project = Projects.objects.create(
            user=self.user, name="Autumn", context=self.work
        )
        self.personal_project = Projects.objects.create(
            user=self.user, name="Training", context=self.personal
        )
        now = timezone.now().replace(microsecond=0)
        self.work_timer = Sessions.objects.create(
            user=self.user,
            project=self.work_project,
            start_time=now - timedelta(minutes=20),
            end_time=None,
            is_active=True,
            note="**Working** <script>alert(1)</script>",
        )
        self.personal_timer = Sessions.objects.create(
            user=self.user,
            project=self.personal_project,
            start_time=now - timedelta(minutes=10),
            end_time=None,
            is_active=True,
        )
        self.completed = Sessions.objects.create(
            user=self.user,
            project=self.work_project,
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
            is_active=False,
            note="Hello **world** <script>bad()</script>",
        )
        self.client.force_login(self.user)


    def test_preferences_reject_foreign_context_and_invalid_slider_step(self):
        response = self.client.patch(
            "/api/v2/me/preferences/",
            data={"active_context_id": self.other_context.pk},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.patch(
            "/api/v2/me/preferences/",
            data={"background_dimming": 63},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


    def test_note_html_is_opt_in_and_sanitized(self):
        default = self.client.get("/api/v2/sessions/").json()["sessions"][0]
        self.assertNotIn("note", default)
        self.assertNotIn("note_html", default)

        included = self.client.get(
            "/api/v2/sessions/", {"include": "note,note_html"}
        ).json()["sessions"][0]
        self.assertEqual(included["note"], self.completed.note)
        self.assertIn("<strong>world</strong>", included["note_html"])
        self.assertNotIn("<script", included["note_html"])

        timer = self.client.get(
            "/api/v2/timers/", {"include": "note_html", "context": self.work.pk}
        ).json()["timers"][0]
        self.assertIn("note", timer)
        self.assertIn("note_html", timer)
        self.assertNotIn("<script", timer["note_html"])

    def test_timers_etag_returns_304_and_varies_by_context(self):
        work = self.client.get("/api/v2/timers/", {"context": self.work.pk})
        self.assertEqual(work.status_code, 200)
        self.assertTrue(work["ETag"].startswith('W/"'))
        cached = self.client.get(
            "/api/v2/timers/",
            {"context": self.work.pk},
            HTTP_IF_NONE_MATCH=work["ETag"],
        )
        self.assertEqual(cached.status_code, 304)
        personal = self.client.get(
            "/api/v2/timers/", {"context": self.personal.pk}
        )
        self.assertNotEqual(work["ETag"], personal["ETag"])

    def test_timers_count_running_timers_outside_the_context(self):
        work = self.client.get("/api/v2/timers/", {"context": self.work.pk})
        self.assertEqual(
            [timer["id"] for timer in work.json()["timers"]], [self.work_timer.pk]
        )
        self.assertEqual(work.json()["outside_context_count"], 1)
        self.assertEqual(
            self.client.get("/api/v2/timers/").json()["outside_context_count"], 0
        )

        # Starting a timer elsewhere changes the count, so the ETag moves.
        Sessions.objects.create(
            user=self.user,
            project=self.personal_project,
            start_time=timezone.now(),
            end_time=None,
            is_active=True,
        )
        again = self.client.get(
            "/api/v2/timers/",
            {"context": self.work.pk},
            HTTP_IF_NONE_MATCH=work["ETag"],
        )
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["outside_context_count"], 2)
