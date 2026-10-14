import base64
import os
import tempfile
from datetime import timedelta
from unittest import mock
from uuid import uuid4

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import StreamingHttpResponse
from django.test import TestCase, override_settings
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator
from rest_framework.test import APIClient

from core.models import (
    Context,
    NotificationEvent,
    Projects,
    PushSubscription,
    ScheduledReminder,
    Sessions,
    TimerReminder,
)
from llm_insights.models import LLMChat, LLMMessage
from users.codex_auth import CodexDeviceCode, CodexDevicePending


class ApiV2WebChunk2Tests(TestCase):
    def setUp(self):
        self.media_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_directory.cleanup)
        self.media_override = override_settings(MEDIA_ROOT=self.media_directory.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.user = User.objects.create_user(
            username="web2", email="web2@example.test", password="secret"
        )
        self.other = User.objects.create_user(
            username="web2-other", email="other@example.test", password="secret"
        )
        self.context = Context.objects.create(user=self.user, name="Work")
        self.other_context = Context.objects.create(user=self.other, name="Other")
        self.project = Projects.objects.create(
            user=self.user, name="Autumn", context=self.context
        )
        self.other_project = Projects.objects.create(
            user=self.other, name="Private", context=self.other_context
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    @staticmethod
    def png_upload(name="image.png"):
        data = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        return SimpleUploadedFile(name, data, content_type="image/png")

    def enable_insights(self, user=None):
        user = user or self.user
        profile = user.profile
        profile.ai_features_enabled = True
        profile.set_api_key("openai", "test-key")
        profile.save()

    def test_authentication_is_required_for_chunk2_endpoints(self):
        anonymous = APIClient()
        for method, path in (
            ("get", "/api/v2/insights/chats/"),
            ("get", "/api/v2/notifications/preferences/"),
            ("get", "/api/v2/notifications/schedules/"),
            ("get", "/api/v2/push/status/"),
            ("get", "/api/v2/reports/weekly-review/"),
            ("get", "/api/v2/me/account/"),
        ):
            with self.subTest(path=path):
                self.assertIn(getattr(anonymous, method)(path).status_code, (401, 403))

    def test_insights_list_detail_delete_and_ownership(self):
        self.enable_insights()
        chat = LLMChat.objects.create(
            user=self.user, title="Useful chat", model="openai:gpt-6-luna"
        )
        LLMMessage.objects.create(
            chat=chat,
            role="assistant",
            content="**Answer** <script>bad()</script>",
            metadata={
                "model": "gpt-6-luna",
                "usage": {"prompt": 4, "response": 2, "cached": 1},
                "sources": [{"link": "https://example.com", "title": "Example"}],
            },
        )
        foreign = LLMChat.objects.create(
            user=self.other, title="Private", model="openai:gpt-6-luna"
        )

        listed = self.client.get("/api/v2/insights/chats/")
        self.assertEqual(listed.status_code, 200)
        ids = [item["id"] for group in listed.json()["groups"] for item in group["chats"]]
        self.assertEqual(ids, [str(chat.pk)])

        detail = self.client.get(f"/api/v2/insights/chats/{chat.pk}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("<strong>Answer</strong>", detail.json()["messages"][0]["html"])
        self.assertNotIn("<script", detail.json()["messages"][0]["html"])
        self.assertEqual(
            self.client.get(f"/api/v2/insights/chats/{foreign.pk}").status_code,
            404,
        )
        self.assertEqual(
            self.client.delete(f"/api/v2/insights/chats/{chat.pk}").status_code,
            204,
        )

    def test_insights_options_and_access_envelope(self):
        denied = self.client.get("/api/v2/insights/options/")
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["error"]["code"], "permission_denied")
        self.enable_insights()
        response = self.client.get("/api/v2/insights/options/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["providers"][0]["provider"], "openai")
        self.assertIn("default_start_date", response.json())

    def test_insights_stream_validates_body_and_chat_ownership(self):
        self.enable_insights()
        chat = LLMChat.objects.create(
            user=self.user, title="Mine", model="openai:gpt-6-luna"
        )
        foreign = LLMChat.objects.create(
            user=self.other, title="Private", model="openai:gpt-6-luna"
        )
        invalid = self.client.post(
            "/api/v2/insights/stream/", {"message": ""}, format="json"
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("message", invalid.json()["error"]["details"])
        self.assertEqual(
            self.client.post(
                "/api/v2/insights/stream/",
                {"chat_id": str(foreign.pk), "message": "No peeking"},
                format="json",
            ).status_code,
            404,
        )

        response_stream = StreamingHttpResponse(
            iter([b'event: done\ndata: {"content":"ok"}\n\n']),
            content_type="text/event-stream",
        )
        with mock.patch(
            "core.api_v2.views.insights.stream_insights_response",
            return_value=response_stream,
        ) as streamer:
            response = self.client.post(
                "/api/v2/insights/stream/",
                {
                    "chat_id": str(chat.pk),
                    "message": "Summarise",
                    "provider": "openai",
                    "model": "gpt-6-luna",
                    "related": True,
                    "project_name": "Autumn",
                    "start_date": "2026-10-01",
                    "end_date": "2026-10-14",
                    "context": self.context.pk,
                    "tags": [],
                    "include_projects": [self.project.pk],
                    "exclude_projects": [],
                },
                format="json",
            )
        self.assertEqual(response.status_code, 200)
        request, passed_chat_id, _access_check = streamer.call_args.args
        self.assertEqual(passed_chat_id, chat.pk)
        self.assertEqual(request.POST["prompt"], "Summarise")
        self.assertEqual(request.POST["related"], "on")
        self.assertEqual(request.POST.getlist("include_projects"), [str(self.project.pk)])

    def test_streaming_schema_documents_event_streams_and_mcp_exclusions(self):
        schema = SchemaGenerator().get_schema(request=None, public=True)
        insights = schema["paths"]["/api/v2/insights/stream/"]["post"]
        response = insights["responses"]["200"]
        self.assertIn("text/event-stream", response["content"])
        for event_name in ("chat", "delta", "done", "error", "keep-alive"):
            self.assertIn(event_name, response["description"])
        self.assertEqual(insights["x-autumn-mcp"], "exclude")
        upload_stream = schema["paths"][
            "/api/v2/import/uploads/{upload_id}/stream/"
        ]["get"]
        self.assertIn(
            "text/event-stream", upload_stream["responses"]["200"]["content"]
        )
        self.assertEqual(upload_stream["x-autumn-mcp"], "exclude")

    def test_notification_preferences_patch_uses_model_validation(self):
        response = self.client.patch(
            "/api/v2/notifications/preferences/",
            {"commitment_checks_enabled": True, "commitment_check_time": "20:30"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["commitment_check_time"], "20:30:00")
        invalid = self.client.patch(
            "/api/v2/notifications/preferences/",
            {"commitment_check_time": "10:00"},
            format="json",
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("commitment_check_time", invalid.json()["error"]["details"])

    def test_schedule_create_list_patch_snooze_delete_and_isolation(self):
        tomorrow = timezone.localdate() + timedelta(days=1)
        create = self.client.post(
            "/api/v2/notifications/schedules/",
            {
                "target": "project",
                "project": self.project.pk,
                "local_date": tomorrow.isoformat(),
                "local_time": "12:00",
                "cadence": "once",
                "message": "Start Autumn",
            },
            format="json",
        )
        self.assertEqual(create.status_code, 201, create.content)
        schedule_id = create.json()["id"]
        listed = self.client.get("/api/v2/notifications/schedules/").json()
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["schedules"][0]["target_resource"]["id"], self.project.pk)

        foreign = self.client.post(
            "/api/v2/notifications/schedules/",
            {
                "target": "project",
                "project": self.other_project.pk,
                "local_date": tomorrow.isoformat(),
                "local_time": "12:00",
                "cadence": "once",
            },
            format="json",
        )
        self.assertEqual(foreign.status_code, 400)
        self.assertIn("project", foreign.json()["error"]["details"])

        missing_project = self.client.post(
            "/api/v2/notifications/schedules/",
            {
                "target": "project",
                "local_date": tomorrow.isoformat(),
                "local_time": "12:00",
                "cadence": "once",
            },
            format="json",
        )
        self.assertEqual(missing_project.status_code, 400)

        other_client = APIClient()
        other_client.force_authenticate(self.other)
        other_schedule = other_client.post(
            "/api/v2/notifications/schedules/",
            {
                "target": "project",
                "project": self.other_project.pk,
                "local_date": tomorrow.isoformat(),
                "local_time": "13:00",
                "cadence": "once",
            },
            format="json",
        )
        self.assertEqual(other_schedule.status_code, 201, other_schedule.content)
        foreign_id = other_schedule.json()["id"]
        foreign_version = other_schedule.json()["version"]
        self.assertEqual(
            self.client.patch(
                f"/api/v2/notifications/schedules/{foreign_id}",
                {"message": "Mine now", "version": foreign_version},
                format="json",
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                f"/api/v2/notifications/schedules/{foreign_id}/snooze/",
                {"choice": "15m", "version": foreign_version},
                format="json",
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.delete(
                f"/api/v2/notifications/schedules/{foreign_id}",
                {"version": foreign_version},
                format="json",
            ).status_code,
            404,
        )

        patched = self.client.patch(
            f"/api/v2/notifications/schedules/{schedule_id}",
            {"message": "Updated", "version": create.json()["version"]},
            format="json",
        )
        self.assertEqual(patched.status_code, 200, patched.content)
        snoozed = self.client.post(
            f"/api/v2/notifications/schedules/{schedule_id}/snooze/",
            {"choice": "15m", "version": patched.json()["version"]},
            format="json",
        )
        self.assertEqual(snoozed.status_code, 200, snoozed.content)
        self.assertEqual(
            self.client.delete(
                f"/api/v2/notifications/schedules/{schedule_id}",
                {"version": snoozed.json()["version"]},
                format="json",
            ).status_code,
            204,
        )

    def test_push_status_contains_only_public_configuration(self):
        response = self.client.get("/api/v2/push/status/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("public_key", response.json())
        self.assertNotIn("private_key", response.json())
        invalid = self.client.post(
            "/api/v2/push/subscriptions/",
            {
                "endpoint": "https://example.com/push",
                "keys": {"p256dh": "bad", "auth": "bad"},
            },
            format="json",
        )
        self.assertEqual(invalid.status_code, 400)

    @override_settings(PUSH_ALLOWED_ENDPOINT_SUFFIXES=("example.test",))
    def test_push_subscribe_unsubscribe_test_and_ownership(self):
        p256dh = base64.urlsafe_b64encode(b"\x04" + b"p" * 64).rstrip(b"=").decode()
        auth = base64.urlsafe_b64encode(b"a" * 16).rstrip(b"=").decode()
        endpoint = "https://push.example.test/subscriptions/mine"
        subscribed = self.client.post(
            "/api/v2/push/subscriptions/",
            {"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}},
            format="json",
        )
        self.assertEqual(subscribed.status_code, 201, subscribed.content)
        self.assertTrue(
            PushSubscription.objects.get(pk=subscribed.json()["id"]).active
        )

        other_client = APIClient()
        other_client.force_authenticate(self.other)
        foreign_endpoint = "https://push.example.test/subscriptions/foreign"
        foreign = other_client.post(
            "/api/v2/push/subscriptions/",
            {
                "endpoint": foreign_endpoint,
                "keys": {"p256dh": p256dh, "auth": auth},
            },
            format="json",
        )
        self.assertEqual(foreign.status_code, 201, foreign.content)
        not_removed = self.client.delete(
            "/api/v2/push/subscriptions/",
            {"endpoint": foreign_endpoint},
            format="json",
        )
        self.assertEqual(not_removed.json(), {"removed": False})
        self.assertTrue(PushSubscription.objects.get(pk=foreign.json()["id"]).active)

        removed = self.client.delete(
            "/api/v2/push/subscriptions/",
            {"endpoint": endpoint},
            format="json",
        )
        self.assertEqual(removed.json(), {"removed": True})
        queued = self.client.post("/api/v2/push/test/", {}, format="json")
        self.assertEqual(queued.status_code, 202)
        event = NotificationEvent.objects.get(pk=queued.json()["event_id"])
        self.assertEqual(event.user, self.user)
        self.assertEqual(
            self.client.post(
                "/api/v2/push/test/", {"endpoint": endpoint}, format="json"
            ).status_code,
            400,
        )

    def test_weekly_review_returns_every_summary_lane(self):
        response = self.client.get(
            "/api/v2/reports/weekly-review/", {"week": "2026-10-14"}
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["week_start"], "2026-10-12")
        for key in (
            "window_start",
            "window_end",
            "timezone",
            "total_minutes",
            "duration_label",
            "project_count",
            "session_count",
            "per_project",
            "met_count",
            "eligible_count",
            "details",
        ):
            self.assertIn(key, response.json())
        invalid = self.client.get(
            "/api/v2/reports/weekly-review/", {"week": "not-a-date"}
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("week", invalid.json()["error"]["details"])

    def test_account_and_api_keys_are_owned_and_write_only(self):
        response = self.client.patch(
            "/api/v2/me/account/",
            {
                "username": "web2-renamed",
                "email": "renamed@example.test",
                "first_name": "Autumn",
                "last_name": "User",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.other.refresh_from_db()
        self.assertEqual(self.other.username, "web2-other")

        denied = self.client.put(
            "/api/v2/me/api-keys/openai", {"key": "secret"}, format="json"
        )
        self.assertEqual(denied.status_code, 403)
        self.user.profile.ai_features_enabled = True
        self.user.profile.save(update_fields=["ai_features_enabled"])
        configured = self.client.put(
            "/api/v2/me/api-keys/openai", {"key": "secret"}, format="json"
        )
        self.assertEqual(configured.json(), {"configured": True})
        self.assertNotIn("secret", configured.content.decode())
        cleared = self.client.delete("/api/v2/me/api-keys/openai")
        self.assertEqual(cleared.json(), {"configured": False})
        self.assertEqual(
            self.client.put(
                "/api/v2/me/api-keys/unknown", {"key": "secret"}, format="json"
            ).status_code,
            404,
        )
        duplicate = self.client.patch(
            "/api/v2/me/account/",
            {"username": self.other.username},
            format="json",
        )
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("username", duplicate.json()["error"]["details"])

    def test_account_media_device_login_and_social_accounts(self):
        avatar = self.client.put(
            "/api/v2/me/avatar/",
            {"image": self.png_upload("avatar.png")},
            format="multipart",
        )
        self.assertEqual(avatar.status_code, 200, avatar.content)
        self.assertIn("profile_pics", avatar.json()["url"])
        self.assertEqual(self.client.delete("/api/v2/me/avatar/").status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.image.name, "default.jpg")

        background = self.client.put(
            "/api/v2/me/background/",
            {"image": self.png_upload("background.png")},
            format="multipart",
        )
        self.assertEqual(background.status_code, 200, background.content)
        download = self.client.get("/api/v2/me/background/download/")
        self.assertEqual(download.status_code, 200)
        self.assertIn("attachment", download["Content-Disposition"])
        self.assertTrue(b"".join(download.streaming_content))
        self.assertEqual(
            self.client.delete("/api/v2/me/background/").json(), {"url": None}
        )

        self.user.profile.ai_features_enabled = True
        self.user.profile.save(update_fields=["ai_features_enabled"])
        code = CodexDeviceCode(
            verification_url="https://auth.example.test/device",
            user_code="ABCD-EFGH",
            device_auth_id="server-poll-secret",
            interval=5,
            expires_at="2026-10-14T18:00:00+02:00",
        )
        with mock.patch(
            "core.api_v2.views.account.start_device_code_login", return_value=code
        ):
            started = self.client.post("/api/v2/me/chatgpt-login/", {}, format="json")
        self.assertEqual(started.status_code, 201)
        self.assertEqual(started.json()["user_code"], "ABCD-EFGH")
        self.assertNotIn("device_auth_id", started.json())
        with mock.patch(
            "core.api_v2.views.account.poll_device_code_login",
            side_effect=CodexDevicePending("waiting"),
        ):
            pending = self.client.get("/api/v2/me/chatgpt-login/")
        self.assertEqual(pending.status_code, 202)
        self.assertNotIn("device_auth_id", pending.json())
        self.assertEqual(
            self.client.delete("/api/v2/me/chatgpt-login/").json(),
            {"status": "disconnected"},
        )

        own_social = SocialAccount.objects.create(
            user=self.user,
            provider="google",
            uid="own-google",
            extra_data={"email": "web2@example.test"},
        )
        foreign_social = SocialAccount.objects.create(
            user=self.other,
            provider="google",
            uid="foreign-google",
        )
        social = self.client.get("/api/v2/me/social-accounts/")
        self.assertEqual(social.status_code, 200)
        google = next(
            item for item in social.json()["accounts"] if item["provider"] == "google"
        )
        self.assertTrue(google["connected"])
        disconnected = self.client.delete("/api/v2/me/social-accounts/google")
        self.assertEqual(disconnected.status_code, 204, disconnected.content)
        self.assertFalse(SocialAccount.objects.filter(pk=own_social.pk).exists())
        self.assertTrue(SocialAccount.objects.filter(pk=foreign_social.pk).exists())

    def test_timer_start_reminder_is_atomic_replay_safe_and_embedded(self):
        client_uuid = str(uuid4())
        payload = {
            "project_id": self.project.pk,
            "uuid": client_uuid,
            "notify_on_auto_stop": True,
            "reminder": {
                "mode": "after",
                "amount": 15,
                "unit": "minutes",
                "message": "Check in",
            },
        }
        first = self.client.post("/api/v2/timers/", payload, format="json")
        self.assertEqual(first.status_code, 201, first.content)
        retry = self.client.post("/api/v2/timers/", payload, format="json")
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(TimerReminder.objects.count(), 1)
        listed = self.client.get("/api/v2/timers/", {"include": "note,reminders"})
        self.assertTrue(listed.json()["timers"][0]["notify_on_auto_stop"])
        self.assertEqual(len(listed.json()["timers"][0]["active_reminders"]), 1)
        reminder = TimerReminder.objects.get()
        etag = listed["ETag"]
        reminder.next_fire_at += timedelta(minutes=1)
        reminder.save(update_fields=["next_fire_at"])
        changed = self.client.get(
            "/api/v2/timers/",
            {"include": "note,reminders"},
            HTTP_IF_NONE_MATCH=etag,
        )
        self.assertEqual(changed.status_code, 200)
        self.assertNotEqual(changed["ETag"], etag)

        without_reminders = self.client.get("/api/v2/timers/")
        reminder.next_fire_at += timedelta(minutes=1)
        reminder.save(update_fields=["next_fire_at"])
        unchanged = self.client.get(
            "/api/v2/timers/", HTTP_IF_NONE_MATCH=without_reminders["ETag"]
        )
        self.assertEqual(unchanged.status_code, 304)

        invalid = self.client.post(
            "/api/v2/timers/",
            {
                "project_id": self.project.pk,
                "reminder": {"mode": "after", "amount": -1, "unit": "minutes"},
            },
            format="json",
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(Sessions.objects.filter(user=self.user).count(), 1)

        missing_offset = self.client.post(
            "/api/v2/timers/",
            {
                "project_id": self.project.pk,
                "reminder": {"mode": "at", "at": "2026-10-15T12:00:00"},
            },
            format="json",
        )
        self.assertEqual(missing_offset.status_code, 400)
        self.assertIn("at", missing_offset.json()["error"]["details"]["reminder"])
        self.assertEqual(Sessions.objects.filter(user=self.user).count(), 1)

    def test_timer_stop_celebration_validation_and_ownership(self):
        now = timezone.now().replace(microsecond=0)
        timer = Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=now - timedelta(minutes=601),
            is_active=True,
        )
        stopped = self.client.post(
            f"/api/v2/timers/{timer.pk}/stop/",
            {"end": now.isoformat()},
            format="json",
        )
        self.assertEqual(stopped.status_code, 200, stopped.content)
        self.assertEqual(stopped.json()["celebration"]["kind"], "progress")
        self.assertIn("reached 10h", stopped.json()["celebration"]["message"])

        active = Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=now,
            is_active=True,
        )
        invalid = self.client.post(
            f"/api/v2/timers/{active.pk}/stop/",
            {"end": (now - timedelta(minutes=1)).isoformat()},
            format="json",
        )
        self.assertEqual(invalid.status_code, 400)
        foreign = Sessions.objects.create(
            user=self.other,
            project=self.other_project,
            start_time=now,
            is_active=True,
        )
        self.assertEqual(
            self.client.post(
                f"/api/v2/timers/{foreign.pk}/stop/", {}, format="json"
            ).status_code,
            404,
        )

    def test_project_completion_has_additive_celebration(self):
        response = self.client.patch(
            f"/api/v2/projects/{self.project.pk}",
            {"status": "complete"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["celebration"]["kind"], "completion")
        self.assertIn("no sessions", response.json()["celebration"]["message"])

    def test_import_upload_is_session_owned_and_one_shot(self):
        upload = SimpleUploadedFile("data.json", b"{}", content_type="application/json")
        response = self.client.post(
            "/api/v2/import/uploads/",
            {"file": upload},
            format="multipart",
        )
        self.assertEqual(response.status_code, 201, response.content)
        upload_id = response.json()["upload_id"]
        staged = self.client.session["api_import_uploads"][upload_id]["file_path"]
        self.assertTrue(os.path.exists(staged))
        isolated_client = APIClient()
        isolated_client.force_authenticate(self.user)
        self.assertEqual(
            isolated_client.get(
                f"/api/v2/import/uploads/{upload_id}/stream/"
            ).status_code,
            404,
        )
        with mock.patch(
            "core.api_v2.import_export.iter_import", return_value=iter(["Imported"])
        ) as importer:
            stream = self.client.get(f"/api/v2/import/uploads/{upload_id}/stream/")
            self.assertEqual(stream.status_code, 200)
            body = b"".join(stream.streaming_content).decode()
        self.assertIn("Imported", body)
        self.assertTrue(importer.call_args.kwargs["merge"])
        self.assertFalse(os.path.exists(staged))
        self.assertEqual(
            self.client.get(f"/api/v2/import/uploads/{upload_id}/stream/").status_code,
            404,
        )
        invalid_context = self.client.post(
            "/api/v2/import/uploads/",
            {
                "file": SimpleUploadedFile(
                    "data.json", b"{}", content_type="application/json"
                ),
                "import_context": self.other_context.pk,
            },
            format="multipart",
        )
        self.assertEqual(invalid_context.status_code, 400)
        self.assertIn("import_context", invalid_context.json()["error"]["details"])

    def test_export_form_options_filter_and_validate(self):
        now = timezone.now().replace(microsecond=0)
        Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=now - timedelta(minutes=30),
            end_time=now,
            is_active=False,
        )
        another = Projects.objects.create(
            user=self.user, name="Elsewhere", context=self.context
        )
        Sessions.objects.create(
            user=self.user,
            project=another,
            start_time=now - timedelta(minutes=20),
            end_time=now,
            is_active=False,
        )
        exported = self.client.get(
            "/api/v2/export/", {"project_name": "Aut", "export_format": "2"}
        )
        self.assertEqual(exported.status_code, 200, exported.content)
        self.assertEqual(
            [project["name"] for project in exported.json()["projects"]], ["Autumn"]
        )
        invalid = self.client.get("/api/v2/export/", {"export_format": "3"})
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("export_format", invalid.json()["error"]["details"])
