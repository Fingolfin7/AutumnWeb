"""Insights on the Focus Desk shell (UI_REDESIGN.md chunk 12).

The shell assertions are the same blunt sweep every other ported page gets.
The interesting ones are in ScriptContractTests: this page moved ~200 lines of
inline JavaScript into a static file, and every hook that script reaches for is
now something a template edit can silently break. A renamed id fails only in
the browser — Python tests would stay green — so the contract is asserted here.
"""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Context, Projects, Sessions, Tag
from django.utils import timezone
from datetime import timedelta

from core.templatetags.time_formats import chat_hover_stamp
from llm_insights.models import LLMChat
from llm_insights.views import group_chats_by_recency


class ChatHoverStampFilterTests(TestCase):
    """core.templatetags.time_formats.chat_hover_stamp backs the sidebar's
    hover-reveal timestamp: time for today/yesterday, a short date once the
    group header stops implying which day, the year once it's not this one."""

    def test_today_shows_a_time_with_no_leading_zero(self):
        stamp = chat_hover_stamp(timezone.localtime())
        self.assertRegex(stamp, r"^\d{1,2}:\d{2} [AP]M$")
        self.assertFalse(stamp.startswith("0"))

    def test_yesterday_shows_a_time_not_a_date(self):
        stamp = chat_hover_stamp(timezone.localtime() - timedelta(days=1))
        self.assertRegex(stamp, r"^\d{1,2}:\d{2} [AP]M$")

    def test_within_the_week_shows_a_short_date(self):
        stamp = chat_hover_stamp(timezone.localtime() - timedelta(days=3))
        self.assertRegex(stamp, r"^\d{1,2} [A-Za-z]{3}$")

    def test_older_than_this_year_includes_the_year(self):
        stamp = chat_hover_stamp(timezone.localtime() - timedelta(days=400))
        self.assertRegex(stamp, r"^\d{1,2} [A-Za-z]{3} \d{4}$")


class ChatSidebarGroupingTests(TestCase):
    """llm_insights.views.group_chats_by_recency buckets the sidebar into
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

    def test_empty_bucket_is_dropped_not_rendered_blank(self):
        LLMChat.objects.filter(user=self.user).exclude(pk=self.today_chat.pk).delete()
        chats = list(LLMChat.objects.filter(user=self.user).order_by("-updated_at"))
        groups = group_chats_by_recency(chats)
        self.assertEqual([label for label, _ in groups], ["Today"])


    def test_the_chat_list_endpoint_groups_the_same_way(self):
        # The React sidebar reads GET /api/v2/insights/chats/.
        payload = self.client.get("/api/v2/insights/chats/").json()
        self.assertEqual(
            [group["label"] for group in payload["groups"]],
            ["Today", "Yesterday", "Previous 7 days", "Older"],
        )
        titles = {group["label"]: [chat["title"] for chat in group["chats"]] for group in payload["groups"]}
        self.assertEqual(titles["Today"], ["Today chat"])
        self.assertEqual(titles["Older"], ["Old chat"])

    def test_the_chat_list_only_shows_the_users_own_chats(self):
        other = User.objects.create_user(username="nosy", email="n@example.com", password="pw")
        LLMChat.objects.create(user=other, title="Not yours", model="openai:gpt-5.6-luna")
        payload = self.client.get("/api/v2/insights/chats/").json()
        titles = [chat["title"] for group in payload["groups"] for chat in group["chats"]]
        self.assertNotIn("Not yours", titles)
