import base64
from datetime import timedelta
from uuid import uuid4

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.models import (
    Context,
    NotificationEvent,
    Projects,
    PushSubscription,
    Sessions,
    TimerReminder,
)
from llm_insights.models import LLMChat, LLMMessage


class ApiV2WebChunk2Tests(TestCase):
    def setUp(self):
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

    def enable_insights(self, user=None):
        user = user or self.user
        profile = user.profile
        profile.ai_features_enabled = True
        profile.set_api_key("openai", "test-key")
        profile.save()


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
