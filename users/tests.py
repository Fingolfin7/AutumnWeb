from unittest.mock import Mock, patch
import shutil
import tempfile
from datetime import date
from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from users import codex_auth


class CodexAuthTests(SimpleTestCase):
    def test_shared_profile_token_refresh_saves_encrypted_bundle(self):
        profile = Mock()
        bundle = {"access_token": "old", "refresh_token": "refresh", "id_token": "id"}
        renewed = {**bundle, "access_token": "new"}
        profile.get_api_key.return_value = codex_auth.serialize_token_bundle(bundle)
        with patch("users.codex_auth.access_token_expires_soon", return_value=True), patch(
            "users.codex_auth.refresh_token_bundle", return_value=renewed
        ):
            self.assertEqual(codex_auth.get_profile_access_token(profile), "new")
        profile.set_api_key.assert_called_once_with("openai_chatgpt", codex_auth.serialize_token_bundle(renewed))
        profile.save.assert_called_once_with(update_fields=["openai_chatgpt_token_enc"])

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
        self.override = override_settings(
            MEDIA_ROOT=self.media_root,
            USE_S3=False,
            STORAGES={
                "default": {
                    "BACKEND": "django.core.files.storage.FileSystemStorage",
                },
                "staticfiles": {
                    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
                },
            },
        )
        self.override.enable()
        self.user = User.objects.create_user(
            username="profile-user",
            email="profile@example.com",
            password="test-pass-123",
        )
        # AI features are off by default since the hardening slice; these
        # tests exercise API-key and insights flows, which are gated on it.
        self.user.profile.ai_features_enabled = True
        self.user.profile.set_api_key("openai", "test-openai-key")
        self.user.profile.save(
            update_fields=["ai_features_enabled", "openai_api_key_enc"]
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

    def test_typesafe_api_key_is_encrypted_and_can_be_cleared(self):
        profile = self.user.profile
        profile.set_api_key("typesafe", "typesafe-production-key")
        profile.save(update_fields=["typesafe_api_key_enc"])

        profile.refresh_from_db()
        self.assertEqual(profile.get_api_key("typesafe"), "typesafe-production-key")
        self.assertNotEqual(bytes(profile.typesafe_api_key_enc), b"typesafe-production-key")

        profile.set_api_key("typesafe", None)
        profile.save(update_fields=["typesafe_api_key_enc"])
        profile.refresh_from_db()
        self.assertIsNone(profile.get_api_key("typesafe"))

    def test_profile_default_date_range_supports_each_requested_unit(self):
        profile = self.user.profile
        reference_date = date(2026, 5, 13)
        expected_starts = {
            "days": date(2026, 5, 3),
            "weeks": date(2026, 3, 4),
            "months": date(2025, 7, 13),
            "years": date(2016, 5, 13),
            "month_to_date": date(2026, 5, 1),
            "quarter_to_date": date(2026, 4, 1),
            "year_to_date": date(2026, 1, 1),
        }

        for unit, expected_start in expected_starts.items():
            with self.subTest(unit=unit):
                profile.default_filter_value = 10
                profile.default_filter_unit = unit
                self.assertEqual(
                    profile.default_filter_date_range(reference_date),
                    (expected_start, reference_date),
                )

    def test_image_url_uses_active_storage_for_default_image(self):
        profile = self.user.profile
        profile.image = None

        self.assertEqual(profile.image_url, "/media/default.jpg")


    # ---- the React Profile page's endpoints ---------------------------------
    # (these replace the tests of the old server-rendered profile form)

    def _api(self):
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(self.user)
        return client

    def test_account_avatar_background_and_api_key_save_through_their_endpoints(self):
        api = self._api()
        account = api.patch(
            "/api/v2/me/account/",
            {"username": "updated-user", "email": "updated@example.com"},
            format="json",
        )
        self.assertEqual(account.status_code, 200, account.content)
        avatar = api.put("/api/v2/me/avatar/", {"image": self._profile_image()}, format="multipart")
        self.assertEqual(avatar.status_code, 200, avatar.content)
        prefs = api.patch(
            "/api/v2/me/preferences/",
            {"automatic_background": True, "bing_background": True},
            format="json",
        )
        self.assertEqual(prefs.status_code, 200, prefs.content)
        key = api.put("/api/v2/me/api-keys/openai", {"key": "profile-openai-key"}, format="json")
        self.assertEqual(key.status_code, 200, key.content)

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

    def test_the_retired_typesafe_key_is_not_exposed_or_changed(self):
        profile = self.user.profile
        profile.set_api_key("typesafe", "legacy-key")
        profile.save(update_fields=["typesafe_api_key_enc"])
        api = self._api()

        preferences = api.get("/api/v2/me/preferences/")
        self.assertNotIn("typesafe", preferences.json()["configured_api_keys"])
        self.assertNotIn("legacy-key", preferences.content.decode())
        for method in (api.put, api.delete):
            response = method("/api/v2/me/api-keys/typesafe", {"key": "ignored"}, format="json")
            self.assertEqual(response.status_code, 404)
        profile.refresh_from_db()
        self.assertEqual(profile.get_api_key("typesafe"), "legacy-key")

    def test_removing_the_background_image_clears_the_field_and_deletes_the_file_after_commit(self):
        profile = self.user.profile
        profile.background_image = self._profile_image()
        profile.save(update_fields=["background_image"])
        old_image_name = profile.background_image.name
        storage = profile.background_image.storage
        self.assertTrue(storage.exists(old_image_name))

        with self.captureOnCommitCallbacks(execute=True):
            response = self._api().delete("/api/v2/me/background/")

        self.assertEqual(response.status_code, 200, response.content)
        profile.refresh_from_db()
        self.assertFalse(profile.background_image)
        self.assertFalse(storage.exists(old_image_name))

    def test_filter_and_chart_defaults_are_saved(self):
        profile = self.user.profile
        profile.default_filter_value = 6
        profile.insights_default_filter_value = 3
        profile.save()

        response = self._api().patch(
            "/api/v2/me/preferences/",
            {
                "default_filter_unit": "quarter_to_date",
                "insights_default_filter_unit": "year_to_date",
                "default_chart_project_count": 12,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        profile.refresh_from_db()
        self.assertEqual(profile.default_filter_value, 6)
        self.assertEqual(profile.default_filter_unit, "quarter_to_date")
        self.assertEqual(profile.insights_default_filter_value, 3)
        self.assertEqual(profile.insights_default_filter_unit, "year_to_date")
        self.assertEqual(profile.default_chart_project_count, 12)

    def test_charts_use_profile_defaults_until_dates_are_explicit(self):
        # The profile side: saved defaults decide the range. The Charts page
        # takes it from /api/v2/me/ (and the SPA bootstrap) and lets explicit
        # dates in its URL override it, which is client behaviour.
        profile = self.user.profile
        profile.default_filter_value = 2
        profile.default_filter_unit = "quarter_to_date"
        profile.default_chart_project_count = 11
        profile.save()

        expected_start, expected_end = profile.default_filter_date_range()
        me = self._api().get("/api/v2/me/").json()
        self.assertEqual(me["default_chart_start_date"], expected_start.isoformat())
        self.assertEqual(me["default_chart_end_date"], expected_end.isoformat())
        preferences = self._api().get("/api/v2/me/preferences/").json()
        self.assertEqual(preferences["default_chart_project_count"], 11)
        self.assertEqual(preferences["default_filter_unit"], "quarter_to_date")

    def test_the_insights_default_range_is_separate_from_the_app_range(self):
        profile = self.user.profile
        profile.default_filter_value = 2
        profile.default_filter_unit = "weeks"
        profile.insights_default_filter_value = 3
        profile.insights_default_filter_unit = "year_to_date"
        profile.save()

        expected_start, expected_end = profile.insights_default_filter_date_range()
        app_start, _ = profile.default_filter_date_range()
        options = self._api().get("/api/v2/insights/options/").json()
        self.assertEqual(options["default_start_date"], expected_start.isoformat())
        self.assertEqual(options["default_end_date"], expected_end.isoformat())
        self.assertNotEqual(options["default_start_date"], app_start.isoformat())

    def test_ai_settings_are_refused_and_account_fields_still_save_when_ai_is_disabled(self):
        profile = self.user.profile
        profile.ai_features_enabled = False
        profile.set_api_key("openai", None)
        profile.save(update_fields=["ai_features_enabled", "openai_api_key_enc"])
        api = self._api()

        self.assertEqual(
            api.put("/api/v2/me/api-keys/openai", {"key": "should-not-save"}, format="json").status_code,
            403,
        )
        account = api.patch(
            "/api/v2/me/account/",
            {"username": "updated-user", "email": "updated@example.com"},
            format="json",
        )
        self.assertEqual(account.status_code, 200, account.content)

        self.user.refresh_from_db()
        profile.refresh_from_db()
        self.assertEqual(self.user.username, "updated-user")
        self.assertEqual(self.user.email, "updated@example.com")
        self.assertIsNone(profile.get_api_key("openai"))

    @patch("core.api_v2.views.account.start_device_code_login")
    def test_chatgpt_login_does_not_touch_the_account_and_is_blocked_without_ai(self, start_login):
        start_login.return_value = codex_auth.CodexDeviceCode(
            verification_url="https://auth.openai.com/codex/device",
            user_code="CODE-123",
            device_auth_id="device-auth-1",
            interval=5,
            expires_at="2099-01-01T00:00:00+00:00",
        )
        api = self._api()
        started = api.post("/api/v2/me/chatgpt-login/", {}, format="json")
        self.assertEqual(started.status_code, 201, started.content)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "profile-user")
        self.assertEqual(self.user.email, "profile@example.com")

        start_login.reset_mock()
        profile = self.user.profile
        profile.ai_features_enabled = False
        profile.save()
        blocked = api.post("/api/v2/me/chatgpt-login/", {}, format="json")
        self.assertEqual(blocked.status_code, 403)
        start_login.assert_not_called()
