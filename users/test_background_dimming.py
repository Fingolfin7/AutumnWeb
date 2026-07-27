"""The header's backdrop-dimming slider posts here on every drag."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class SetBackgroundDimmingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="dimmer", email="d@example.com", password="pw"
        )

    def setUp(self):
        self.client.login(username="dimmer", password="pw")

    def url(self):
        return reverse("set_background_dimming")

    def test_saves_the_value(self):
        response = self.client.post(self.url(), {"value": 30})
        self.assertEqual(response.status_code, 204)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.background_dimming, 30)

    def test_clamps_rather_than_rejecting(self):
        """The slider cannot produce these, but a stray request should not be
        able to push the scrim outside the range the profile form enforces."""
        for sent, stored in ((-10, 0), (200, 85)):
            with self.subTest(sent=sent):
                self.client.post(self.url(), {"value": sent})
                self.user.profile.refresh_from_db()
                self.assertEqual(self.user.profile.background_dimming, stored)

    def test_rejects_a_non_integer(self):
        before = self.user.profile.background_dimming
        response = self.client.post(self.url(), {"value": "dark"})
        self.assertEqual(response.status_code, 400)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.background_dimming, before)

    def test_rejects_get(self):
        self.assertEqual(self.client.get(self.url()).status_code, 405)

    def test_requires_login(self):
        self.client.logout()
        response = self.client.post(self.url(), {"value": 10})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_only_touches_the_dimming_field(self):
        """save(update_fields=...) keeps a rapid drag from writing the rest of
        the profile back over whatever another tab may have just changed."""
        profile = self.user.profile
        profile.background_dimming = 55
        profile.save()

        stale = User.objects.get(pk=self.user.pk).profile
        stale.background_dimming = 10  # a stale in-memory copy

        self.client.post(self.url(), {"value": 40})
        profile.refresh_from_db()
        self.assertEqual(profile.background_dimming, 40)


class HeaderControlTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="header", email="h@example.com", password="pw"
        )

    def test_slider_is_in_the_shell_for_signed_in_users(self):
        self.client.login(username="header", password="pw")
        body = self.client.get(reverse("home")).content.decode()
        self.assertIn('id="header-dimming"', body)
        self.assertIn("dim-control", body)
        # it needs a token: there is no surrounding form to supply one
        self.assertIn("csrfmiddlewaretoken", body)

    def test_slider_is_absent_for_anonymous_visitors(self):
        response = self.client.get(reverse("login"))
        self.assertNotIn('id="header-dimming"', response.content.decode())
