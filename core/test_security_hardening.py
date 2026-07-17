"""Regression tests for the security-hardening slice."""

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse

from core.templatetags.markdown_render import markdown as render_markdown
from llm_insights.models import LLMChat


class MarkdownSanitizationTests(TestCase):
    def test_script_and_event_handlers_are_stripped(self):
        rendered = render_markdown(
            'hello <script>alert(1)</script> '
            '<img src="x" onerror="alert(2)"> world'
        )
        self.assertNotIn("<script", rendered)
        self.assertNotIn("onerror", rendered)
        self.assertIn("hello", rendered)
        self.assertIn("world", rendered)

    def test_ordinary_markdown_structures_survive(self):
        rendered = render_markdown(
            "# Title\n\n| a | b |\n| - | - |\n| 1 | 2 |\n\n```\ncode\n```\n\n~~gone~~"
        )
        self.assertIn("<h1>", rendered)
        self.assertIn("<table>", rendered)
        self.assertIn("<code>", rendered)
        self.assertIn("<del>", rendered)


class DeleteChatMethodTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="chat-user", password="x")
        self.user.profile.ai_features_enabled = True
        self.user.profile.save(update_fields=["ai_features_enabled"])
        self.chat = LLMChat.objects.create(user=self.user, title="t")
        self.client.force_login(self.user)

    def test_get_is_rejected_and_post_deletes(self):
        url = reverse("delete_chat", args=[self.chat.id])

        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertTrue(LLMChat.objects.filter(id=self.chat.id).exists())

        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(LLMChat.objects.filter(id=self.chat.id).exists())


class ImportStreamAuthTests(TestCase):
    def test_anonymous_request_is_redirected_to_login(self):
        response = self.client.get(reverse("import_stream"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_non_get_is_rejected(self):
        user = User.objects.create_user(username="import-user", password="x")
        self.client.force_login(user)
        response = self.client.post(reverse("import_stream"))
        self.assertEqual(response.status_code, 405)


class RemovedDebugRoutesTests(TestCase):
    def test_debug_and_token_probe_routes_are_gone(self):
        self.assertEqual(self.client.get("/debug-session/").status_code, 404)
        self.assertEqual(
            self.client.get("/check-auth-token/some-token/").status_code, 404
        )
        for name in ("debug_session", "check-auth-token"):
            with self.assertRaises(NoReverseMatch):
                reverse(name, args=["x"] if "check" in name else None)


class RegistrationGateTests(TestCase):
    def test_registration_is_closed_by_default(self):
        response = self.client.get(reverse("register"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

        self.client.post(
            reverse("register"),
            {"username": "intruder", "password1": "xyzXYZ123!", "password2": "xyzXYZ123!"},
        )
        self.assertFalse(User.objects.filter(username="intruder").exists())

    @override_settings(ALLOW_REGISTRATION=True)
    def test_registration_can_be_enabled_via_setting(self):
        response = self.client.get(reverse("register"))
        self.assertEqual(response.status_code, 200)


class AiFeaturesDefaultTests(TestCase):
    def test_new_accounts_get_no_ai_access(self):
        user = User.objects.create_user(username="fresh-user", password="x")
        self.assertFalse(user.profile.ai_features_enabled)
