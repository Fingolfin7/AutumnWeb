"""Tests for the Focus Desk account pages (UI_REDESIGN.md chunk 11)."""

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse


class UsersShellTests(TestCase):
    def _assert_focus_desk_page(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/base_fd.html")
        self.assertContains(response, "core/css/focus_desk.css")
        self.assertNotContains(response, "core/css/style.css")

    @override_settings(ALLOW_REGISTRATION=True)
    def test_public_account_pages_use_the_focus_desk_shell_only(self):
        for url in (
            reverse("login"),
            reverse("register"),
            reverse("password_reset"),
        ):
            with self.subTest(url=url):
                self._assert_focus_desk_page(self.client.get(url))

    def test_logout_uses_the_focus_desk_shell_only(self):
        user = User.objects.create_user(username="finrod", password="pw")
        self.client.force_login(user)

        self._assert_focus_desk_page(self.client.post(reverse("logout")))

    def test_profile_uses_the_focus_desk_shell_only(self):
        user = User.objects.create_user(username="finrod", password="pw")
        self.client.force_login(user)

        self._assert_focus_desk_page(self.client.get(reverse("profile")))

    def test_anonymous_profile_redirects_to_login(self):
        response = self.client.get(reverse("profile"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)
