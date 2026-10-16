"""Insights on the Focus Desk shell (UI_REDESIGN.md chunk 12).

The shell assertions are the same blunt sweep every other ported page gets.
The interesting ones are in ScriptContractTests: this page moved ~200 lines of
inline JavaScript into a static file, and every hook that script reaches for is
now something a template edit can silently break. A renamed id fails only in
the browser — Python tests would stay green — so the contract is asserted here.
"""

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from datetime import timedelta

from llm_insights.models import LLMChat
from llm_insights.services.chats import group_chats_by_recency


class ChatSidebarGroupingTests(TestCase):
    """llm_insights.services.chats.group_chats_by_recency buckets the sidebar into
    Today / Yesterday / Previous 7 days / Older, the same grouping ChatGPT and
    Claude use for their own chat history."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="sidebargroups", email="g@example.com", password="pw"
        )
        cls.user.profile.ai_features_enabled = True
        cls.user.profile.set_api_key("openai", "test-openai-key")
        cls.user.profile.save()

        now = timezone.now()
        cls.today_chat = LLMChat.objects.create(
            user=cls.user, title="Today chat", model="openai:gpt-5.6-luna"
        )
        cls.yesterday_chat = LLMChat.objects.create(
            user=cls.user, title="Yesterday chat", model="openai:gpt-5.6-luna"
        )
        LLMChat.objects.filter(pk=cls.yesterday_chat.pk).update(
            updated_at=now - timedelta(days=1)
        )
        cls.week_chat = LLMChat.objects.create(
            user=cls.user, title="Week chat", model="openai:gpt-5.6-luna"
        )
        LLMChat.objects.filter(pk=cls.week_chat.pk).update(
            updated_at=now - timedelta(days=3)
        )
        cls.old_chat = LLMChat.objects.create(
            user=cls.user, title="Old chat", model="openai:gpt-5.6-luna"
        )
        LLMChat.objects.filter(pk=cls.old_chat.pk).update(
            updated_at=now - timedelta(days=400)
        )

    def setUp(self):
        self.client.login(username="sidebargroups", password="pw")

    def test_buckets_chats_in_recency_order(self):
        chats = list(LLMChat.objects.filter(user=self.user).order_by("-updated_at"))
        groups = group_chats_by_recency(chats)
        self.assertEqual(
            [label for label, _ in groups],
            ["Today", "Yesterday", "Previous 7 days", "Older"],
        )
        grouped = dict(groups)
        self.assertEqual([c.title for c in grouped["Today"]], ["Today chat"])
        self.assertEqual([c.title for c in grouped["Yesterday"]], ["Yesterday chat"])
        self.assertEqual([c.title for c in grouped["Previous 7 days"]], ["Week chat"])
        self.assertEqual([c.title for c in grouped["Older"]], ["Old chat"])


    def test_the_chat_list_only_shows_the_users_own_chats(self):
        other = User.objects.create_user(username="nosy", email="n@example.com", password="pw")
        LLMChat.objects.create(user=other, title="Not yours", model="openai:gpt-5.6-luna")
        payload = self.client.get("/api/v2/insights/chats/").json()
        titles = [chat["title"] for group in payload["groups"] for chat in group["chats"]]
        self.assertNotIn("Not yours", titles)
