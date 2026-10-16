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


    def test_requires_login(self):
        self.client.logout()
        response = self.client.post(self.url(), {"value": 10})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)
