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

from llm_insights.models import LLMChat


class InsightsDeskTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="insightsdesk", email="i@example.com", password="pw"
        )
        cls.user.profile.ai_features_enabled = True
        cls.user.profile.set_api_key("openai", "test-openai-key")
        cls.user.profile.save()
        cls.context = Context.objects.create(user=cls.user, name="Work")
        cls.tag = Tag.objects.create(user=cls.user, name="deep")
        cls.project = Projects.objects.create(
            user=cls.user, name="Atlas API", context=cls.context
        )
        end = timezone.now() - timedelta(hours=1)
        cls.session = Sessions.objects.create(
            user=cls.user,
            project=cls.project,
            start_time=end - timedelta(minutes=45),
            end_time=end,
            note="a note",
        )

    def setUp(self):
        self.client.login(username="insightsdesk", password="pw")

    def test_renders_on_the_new_shell_only(self):
        response = self.client.get(reverse("insights"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/base.html")
        body = response.content.decode()
        self.assertIn("core/css/focus_desk.css", body)
        self.assertNotIn("core/css/style.css", body)

    def test_does_not_load_the_deleted_chat_stylesheet(self):
        """chat_style.css was folded into focus_desk.css and deleted; a stale
        <link> would 404 rather than fail loudly."""
        body = self.client.get(reverse("insights")).content.decode()
        self.assertNotIn("chat_style.css", body)

    def test_does_not_reload_a_second_jquery(self):
        """The legacy page pulled jQuery 1.7.1 in after the shell's 3.6,
        silently downgrading every script that followed it."""
        body = self.client.get(reverse("insights")).content.decode()
        self.assertNotIn("libs/jquery/1.7.1", body)
        self.assertNotIn("jqueryui/1.8.16", body)

    def test_filters_are_summarised_back_to_the_page(self):
        """Filters live in a sheet now, so a narrowed page has to say so —
        otherwise an empty session set reads as broken rather than narrow."""
        response = self.client.get(reverse("insights"), {"context": self.context.id})
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("filter-pill", body)
        self.assertIn("Work", body)

    def test_empty_state_says_what_to_do(self):
        Sessions.objects.all().delete()
        body = self.client.get(reverse("insights")).content.decode()
        self.assertIn("No sessions match these filters", body)
        self.assertIn(reverse("sessions"), body)

    def test_older_chats_can_be_loaded_in_batches(self):
        LLMChat.objects.bulk_create(
            [
                LLMChat(
                    user=self.user,
                    title=f"Chat {number}",
                    model="openai:gpt-5.6-luna",
                )
                for number in range(25)
            ]
        )

        first_page = self.client.get(reverse("insights"))

        self.assertEqual(len(first_page.context["recent_chats"]), 20)
        self.assertTrue(first_page.context["has_older_chats"])
        self.assertContains(first_page, "Load older chats")
        self.assertContains(first_page, "chat_limit=40")

        expanded_page = self.client.get(reverse("insights"), {"chat_limit": 40})

        self.assertEqual(len(expanded_page.context["recent_chats"]), 25)
        self.assertFalse(expanded_page.context["has_older_chats"])
        self.assertNotContains(expanded_page, "Load older chats")
        self.assertContains(
            expanded_page,
            '?chat_limit=40" class="chat-item',
            count=25,
        )


class ScriptContractTests(TestCase):
    """insights_page.js and insights_stream.js address the page by id/class.

    Renaming any of these breaks the page in the browser while leaving every
    other test green, so they are pinned here.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="insightsjs", email="j@example.com", password="pw"
        )
        cls.user.profile.ai_features_enabled = True
        cls.user.profile.set_api_key("openai", "test-openai-key")
        cls.user.profile.save()
        cls.project = Projects.objects.create(user=cls.user, name="Atlas API")
        end = timezone.now() - timedelta(hours=1)
        Sessions.objects.create(
            user=cls.user,
            project=cls.project,
            start_time=end - timedelta(minutes=30),
            end_time=end,
        )
        cls.chat = LLMChat.objects.create(
            user=cls.user, title="Older chat", model="gemini:gemini-2.0-flash"
        )

    def setUp(self):
        self.client.login(username="insightsjs", password="pw")

    def test_hooks_insights_page_js_depends_on_are_present(self):
        body = self.client.get(reverse("insights")).content.decode()
        for hook in (
            'id="insights-config"',        # the config blob it parses
            'id="provider"',
            'id="model"',
            'id="reasoning_effort"',
            'id="reasoning-effort-field"',
            'id="provider_filter"',        # hidden GET mirrors of the above
            'id="model_filter"',
            'id="reasoning_effort_filter"',
            'id="conversation-container"',
            'id="select-messages-btn"',
            'id="copy-selected-btn"',
            'id="copy-full-chat-btn"',
            'id="toggle-sidebar-btn"',
            'id="prompt"',
            'id="chat-form"',
            'class="chat-sidebar"',
        ):
            with self.subTest(hook=hook):
                self.assertIn(hook, body)

    def test_hooks_insights_stream_js_depends_on_are_present(self):
        body = self.client.get(reverse("insights")).content.decode()
        for hook in (
            'id="token-usage"',
            "chat-list",           # it appends new chats here
            "chat-item-container",
            "chat-title",
            "data-stream-url",     # where it POSTs
            "csrfmiddlewaretoken",
        ):
            with self.subTest(hook=hook):
                self.assertIn(hook, body)

    def test_inline_handlers_resolve_to_exported_functions(self):
        """The five onclick= handlers in the markup are only reachable because
        insights_page.js explicitly puts them on window — it is inside an IIFE.
        deleteChat is the exception: insights_stream.js defines it globally."""
        from pathlib import Path
        from django.conf import settings

        js_dir = Path(settings.BASE_DIR) / "core" / "static" / "core" / "js"
        page_js = (js_dir / "insights_page.js").read_text(encoding="utf-8")
        stream_js = (js_dir / "insights_stream.js").read_text(encoding="utf-8")

        for name in (
            "copyToClipboard",
            "copyFullChat",
            "copySelectedMessages",
            "toggleSelectMode",
            "toggleSidebar",
        ):
            with self.subTest(name=name):
                self.assertIn(f"function {name}", page_js)
                self.assertIn(f"window.{name} = {name};", page_js)

        self.assertIn("function deleteChat", stream_js)

    def test_empty_chat_list_placeholder_is_the_one_the_stream_removes(self):
        """insights_stream.js deletes .chat-list-empty when the first chat is
        created. It used to target .text-muted, a styling class."""
        LLMChat.objects.all().delete()
        body = self.client.get(reverse("insights")).content.decode()
        self.assertIn("chat-list-empty", body)

        from pathlib import Path
        from django.conf import settings

        stream_js = (
            Path(settings.BASE_DIR) / "core" / "static" / "core" / "js" / "insights_stream.js"
        ).read_text(encoding="utf-8")
        self.assertIn("chat-list-empty", stream_js)

    def test_config_blob_carries_what_the_script_reads(self):
        body = self.client.get(reverse("insights")).content.decode()
        self.assertIn("providerModels", body)
        self.assertIn("selectedProvider", body)
        self.assertIn("selectedModel", body)
        self.assertIn("insightsjs", body)  # username, used to label the transcript
