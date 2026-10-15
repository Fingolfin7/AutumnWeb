from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone

from core.models import Context, Projects, Sessions, TimerReminder
from core.services.timer_suggestions import LunaSuggestionResult


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

    def test_authentication_is_required_for_new_get_endpoints(self):
        anonymous = Client()
        for path in (
            "/api/v2/me/preferences/",
            "/api/v2/dashboard/",
            "/api/v2/reports/timeline/",
            "/api/v2/recommendations/timers/",
            "/api/v2/recommendations/luna/",
            f"/api/v2/timers/{self.work_timer.pk}/reminders/",
        ):
            with self.subTest(path=path):
                self.assertIn(anonymous.get(path).status_code, (401, 403))

    def test_preferences_shape_patch_and_profile_context_fallback(self):
        response = self.client.get("/api/v2/me/preferences/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.json()["configured_api_keys"]),
            {"gemini", "openai", "openai_chatgpt", "claude"},
        )
        self.assertEqual(response.json()["background"]["mode"], "none")
        self.assertEqual(len(response.json()["contexts"]), 2)

        response = self.client.patch(
            "/api/v2/me/preferences/",
            data={
                "active_context_id": self.work.pk,
                "background_dimming": 60,
                "default_chart_project_count": 9,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["active_context_id"], self.work.pk)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.active_context_id, self.work.pk)

        session = self.client.session
        session.pop("active_context_id", None)
        session.save()
        # The stored preference scopes server-rendered pages, never the API:
        # `autumn status` and MCP must keep seeing every timer unless they
        # ask for a context.
        timers = self.client.get("/api/v2/timers/").json()["timers"]
        self.assertEqual(len(timers), 2)
        timers = self.client.get("/api/v2/timers/", {"context": self.work.pk}).json()["timers"]
        self.assertEqual([timer["id"] for timer in timers], [self.work_timer.pk])

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

    def test_dashboard_and_timeline_shapes_respect_explicit_context(self):
        dashboard = self.client.get(
            "/api/v2/dashboard/", {"context": self.work.pk}
        )
        self.assertEqual(dashboard.status_code, 200)
        payload = dashboard.json()
        self.assertEqual(
            [timer["id"] for timer in payload["active_timers"]],
            [self.work_timer.pk],
        )
        self.assertIn("note_html", payload["recent_sessions"][0]["sessions"][0])
        self.assertIn("timeline", payload)

        timeline = self.client.get(
            "/api/v2/reports/timeline/",
            {"context": self.work.pk},
        )
        self.assertEqual(timeline.status_code, 200)
        self.assertEqual(
            {lane["project"]["id"] for lane in timeline.json()["lanes"]},
            {self.work_project.pk},
        )

    def test_timeline_validates_date_pair_and_order(self):
        response = self.client.get("/api/v2/reports/timeline/", {"start": "2026-01-01"})
        self.assertEqual(response.status_code, 400)
        response = self.client.get(
            "/api/v2/reports/timeline/",
            {"start": "2026-01-02", "end": "2026-01-01"},
        )
        self.assertEqual(response.status_code, 400)

    def test_timer_suggestions_shape_and_context_validation(self):
        response = self.client.get(
            "/api/v2/recommendations/timers/", {"context": self.work.pk}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {"commitments", "habits", "recent"})
        response = self.client.get(
            "/api/v2/recommendations/timers/", {"context": self.other_context.pk}
        )
        self.assertEqual(response.status_code, 400)

    @patch("core.api_v2.views.recommendations.timer_suggestions.build_luna_suggestions")
    def test_luna_pending_response_has_polling_headers(self, build_luna):
        build_luna.return_value = LunaSuggestionResult(
            suggestions=[], pending=True, advice_status="Working"
        )
        response = self.client.get("/api/v2/recommendations/luna/")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response["Retry-After"], "5")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response.json(), {"suggestions": [], "advice_status": "Working"})

    def test_refresh_requires_csrf_for_session_authentication(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        response = csrf_client.post(
            "/api/v2/recommendations/luna/refresh/",
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_reminder_list_and_idempotent_delete(self):
        reminder = TimerReminder.objects.create(
            session=self.work_timer,
            mode="after",
            next_fire_at=timezone.now() + timedelta(minutes=15),
        )
        path = f"/api/v2/timers/{self.work_timer.pk}/reminders/"
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reminders"][0]["id"], reminder.pk)

        detail = f"{path}{reminder.pk}"
        self.assertEqual(self.client.delete(detail).status_code, 204)
        self.assertEqual(self.client.delete(detail).status_code, 204)
        reminder.refresh_from_db()
        self.assertFalse(reminder.active)

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
