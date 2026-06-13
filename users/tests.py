from unittest.mock import Mock, patch
import shutil
import tempfile
from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from users import codex_auth


class CodexAuthTests(SimpleTestCase):
    @patch("users.codex_auth.requests.post")
    def test_start_device_code_login_returns_session_payload(self, post):
        post.return_value = Mock(
            ok=True,
            json=lambda: {
                "device_auth_id": "device-auth-1",
                "user_code": "CODE-123",
                "interval": "3",
            },
        )

        device_code = codex_auth.start_device_code_login()

        self.assertEqual(device_code.user_code, "CODE-123")
        self.assertEqual(device_code.device_auth_id, "device-auth-1")
        self.assertEqual(device_code.interval, 3)
        self.assertEqual(device_code.verification_url, "https://auth.openai.com/codex/device")

    @patch("users.codex_auth.requests.post")
    def test_poll_device_code_login_exchanges_code_for_tokens(self, post):
        poll_response = Mock(
            ok=True,
            status_code=200,
            json=lambda: {
                "authorization_code": "auth-code",
                "code_verifier": "verifier",
            },
        )
        exchange_response = Mock(
            ok=True,
            status_code=200,
            json=lambda: {
                "id_token": "id-token",
                "access_token": "access-token",
                "refresh_token": "refresh-token",
            },
        )
        post.side_effect = [poll_response, exchange_response]

        bundle = codex_auth.poll_device_code_login(
            {
                "device_auth_id": "device-auth-1",
                "user_code": "CODE-123",
            }
        )

        self.assertEqual(bundle["access_token"], "access-token")
        self.assertEqual(bundle["refresh_token"], "refresh-token")


class ProfileSaveTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()
        self.user = User.objects.create_user(
            username="profile-user",
            email="profile@example.com",
            password="test-pass-123",
        )
        self.client.login(username="profile-user", password="test-pass-123")

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)

    def _profile_image(self):
        buf = BytesIO()
        Image.new("RGB", (12, 12), color=(0, 128, 170)).save(buf, format="PNG")
        return SimpleUploadedFile(
            "avatar.png",
            buf.getvalue(),
            content_type="image/png",
        )

    def test_update_profile_saves_image_account_background_and_api_key_together(self):
        response = self.client.post(
            reverse("profile"),
            data={
                "username": "updated-user",
                "email": "updated@example.com",
                "image": self._profile_image(),
                "automatic_background": "on",
                "background_choice": "bing",
                "openai_api_key": "profile-openai-key",
            },
        )

        self.assertRedirects(response, reverse("profile"))
        self.user.refresh_from_db()
        profile = self.user.profile
        profile.refresh_from_db()
        self.assertEqual(self.user.username, "updated-user")
        self.assertEqual(self.user.email, "updated@example.com")
        self.assertTrue(profile.image.name.startswith("profile_pics/"))
        self.assertTrue(profile.automatic_background)
        self.assertTrue(profile.bing_background)
        self.assertFalse(profile.nasa_apod_background)
        self.assertEqual(profile.get_api_key("openai"), "profile-openai-key")

    def test_profile_hides_and_ignores_ai_settings_when_disabled(self):
        profile = self.user.profile
        profile.ai_features_enabled = False
        profile.save()

        response = self.client.get(reverse("profile"))

        self.assertNotContains(response, "LLM Connections")
        self.assertNotContains(response, "Gemini API Key")
        self.assertNotContains(response, "Use Codex Login")

        response = self.client.post(
            reverse("profile"),
            data={
                "username": "updated-user",
                "email": "updated@example.com",
                "openai_api_key": "should-not-save",
            },
        )

        self.assertRedirects(response, reverse("profile"))
        self.user.refresh_from_db()
        profile.refresh_from_db()
        self.assertEqual(self.user.username, "updated-user")
        self.assertEqual(self.user.email, "updated@example.com")
        self.assertIsNone(profile.get_api_key("openai"))

    @patch("users.views.start_device_code_login")
    def test_codex_action_does_not_run_general_profile_save(self, start_login):
        start_login.return_value = codex_auth.CodexDeviceCode(
            verification_url="https://auth.openai.com/codex/device",
            user_code="CODE-123",
            device_auth_id="device-auth-1",
            interval=5,
            expires_at="2099-01-01T00:00:00+00:00",
        )

        response = self.client.post(
            reverse("profile"),
            data={
                "start_openai_chatgpt_login": "1",
                "username": "should-not-save",
                "email": "should-not-save@example.com",
            },
        )

        self.assertRedirects(response, reverse("profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "profile-user")
        self.assertEqual(self.user.email, "profile@example.com")

    @patch("users.views.start_device_code_login")
    def test_codex_action_is_blocked_when_ai_features_disabled(self, start_login):
        profile = self.user.profile
        profile.ai_features_enabled = False
        profile.save()

        response = self.client.post(
            reverse("profile"),
            data={
                "start_openai_chatgpt_login": "1",
                "username": "should-not-save",
                "email": "should-not-save@example.com",
            },
        )

        self.assertRedirects(response, reverse("profile"))
        start_login.assert_not_called()
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "profile-user")
        self.assertEqual(self.user.email, "profile@example.com")
