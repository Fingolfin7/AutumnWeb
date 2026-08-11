from allauth.account.models import EmailAddress
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.conf import settings
from django.contrib.auth.models import AnonymousUser, User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from lxml import html

from users.adapters import AutumnAccountAdapter, AutumnSocialAccountAdapter


SOCIAL_PROVIDER_SETTINGS = {
    "google": {
        "SCOPE": ["openid", "profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
        "OAUTH_PKCE_ENABLED": True,
        "APP": {"client_id": "google-client", "secret": "google-secret", "key": ""},
    },
    "github": {
        "SCOPE": ["user:email"],
        "APP": {"client_id": "github-client", "secret": "github-secret", "key": ""},
    },
}


@override_settings(
    GOOGLE_AUTH_ENABLED=True,
    GITHUB_AUTH_ENABLED=True,
    SOCIALACCOUNT_PROVIDERS=SOCIAL_PROVIDER_SETTINGS,
)
class SocialAuthUITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="social-user",
            email="social@example.com",
            password="test-password",
        )

    def test_login_offers_enabled_providers_with_post_actions(self):
        response = self.client.get(reverse("login"))

        self.assertContains(response, "Continue with Google")
        self.assertContains(response, "Continue with GitHub")
        self.assertContains(response, reverse("google_login"))
        self.assertContains(response, reverse("github_login"))

        document = html.fromstring(response.content)
        provider_forms = document.xpath(
            "//form[contains(@action, '/accounts/google/login/') or "
            "contains(@action, '/accounts/github/login/')]"
        )
        self.assertEqual(len(provider_forms), 2)
        for form in provider_forms:
            field_names = set(form.xpath(".//input/@name"))
            self.assertEqual(field_names, {"csrfmiddlewaretoken"})

    def test_provider_login_starts_oauth_using_post(self):
        google = self.client.post(reverse("google_login"))
        github = self.client.post(reverse("github_login"))

        self.assertEqual(google.status_code, 302)
        self.assertIn("accounts.google.com", google.url)
        self.assertEqual(github.status_code, 302)
        self.assertIn("github.com/login/oauth/authorize", github.url)

    def test_social_signup_requires_and_queries_for_email(self):
        self.assertTrue(settings.SOCIALACCOUNT_EMAIL_REQUIRED)
        self.assertTrue(settings.SOCIALACCOUNT_QUERY_EMAIL)

    def test_profile_offers_connections_for_enabled_providers(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("profile"))

        self.assertContains(response, "Connect Google")
        self.assertContains(response, "Connect GitHub")
        self.assertContains(response, 'process=connect', count=2)

    def test_profile_displays_and_disconnects_connected_provider(self):
        account = SocialAccount.objects.create(
            user=self.user,
            provider="google",
            uid="google-123",
            extra_data={"email": "social@gmail.example"},
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("profile"))
        self.assertContains(response, "Connected as social@gmail.example")

        response = self.client.post(
            reverse("disconnect_social_account", args=["google"]),
        )

        self.assertRedirects(response, reverse("profile"))
        self.assertFalse(SocialAccount.objects.filter(pk=account.pk).exists())

    def test_last_provider_cannot_be_removed_without_a_password(self):
        social_only_user = User.objects.create_user(
            username="social-only",
            email="social-only@example.com",
            password=None,
        )
        account = SocialAccount.objects.create(
            user=social_only_user,
            provider="github",
            uid="github-123",
        )
        self.client.force_login(social_only_user)

        response = self.client.post(
            reverse("disconnect_social_account", args=["github"]),
        )

        self.assertRedirects(response, reverse("profile"))
        self.assertTrue(SocialAccount.objects.filter(pk=account.pk).exists())


class SocialAuthPolicyTests(TestCase):
    def _request(self):
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    @override_settings(ALLOW_REGISTRATION=False)
    def test_all_signup_paths_follow_registration_setting_when_closed(self):
        request = self._request()
        sociallogin = SocialLogin(
            user=User(username="new-user"),
            account=SocialAccount(provider="google", uid="new-google-user"),
        )

        self.assertFalse(AutumnAccountAdapter(request).is_open_for_signup(request))
        self.assertFalse(
            AutumnSocialAccountAdapter(request).is_open_for_signup(
                request,
                sociallogin,
            )
        )

    @override_settings(ALLOW_REGISTRATION=True)
    def test_all_signup_paths_follow_registration_setting_when_open(self):
        request = self._request()
        sociallogin = SocialLogin(
            user=User(username="new-user"),
            account=SocialAccount(provider="github", uid="new-github-user"),
        )

        self.assertTrue(AutumnAccountAdapter(request).is_open_for_signup(request))
        self.assertTrue(
            AutumnSocialAccountAdapter(request).is_open_for_signup(
                request,
                sociallogin,
            )
        )

    def test_existing_email_is_not_silently_merged(self):
        User.objects.create_user(
            username="local-user",
            email="owner@example.com",
            password="test-password",
        )
        request = self._request()
        sociallogin = SocialLogin(
            user=User(username="google-user"),
            account=SocialAccount(provider="google", uid="google-user"),
            email_addresses=[
                EmailAddress(email="OWNER@example.com", verified=True),
            ],
        )

        with self.assertRaises(ImmediateHttpResponse) as raised:
            AutumnSocialAccountAdapter(request).pre_social_login(
                request,
                sociallogin,
            )

        self.assertEqual(raised.exception.response.status_code, 302)
        self.assertEqual(raised.exception.response.url, reverse("login"))


@override_settings(
    GOOGLE_AUTH_ENABLED=False,
    GITHUB_AUTH_ENABLED=False,
)
class DisabledSocialAuthTests(TestCase):
    def test_disabled_providers_are_hidden_and_direct_requests_fail_safely(self):
        login_page = self.client.get(reverse("login"))
        self.assertNotContains(login_page, "Continue with Google")
        self.assertNotContains(login_page, "Continue with GitHub")

        for route_name in ("google_login", "github_login"):
            with self.subTest(route_name=route_name):
                response = self.client.post(reverse(route_name))
                self.assertRedirects(response, reverse("login"))
