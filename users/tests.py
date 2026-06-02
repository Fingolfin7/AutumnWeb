from unittest.mock import Mock, patch

from django.test import SimpleTestCase

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
