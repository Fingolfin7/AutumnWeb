import re
import smtplib
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PasswordResetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="finrod", email="finrod@example.com", password="old-password",
        )

    def test_password_reset_round_trip(self):
        response = self.client.post(reverse("password_reset"), {"email": self.user.email})
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        link = re.search(r"https?://[^\s]+/password-reset/confirm/[^\s]+", message.body).group()
        self.assertIn(link, message.alternatives[0].content)
        response = self.client.get(urlsplit(link).path, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["validlink"])
        set_password_url = response.redirect_chain[-1][0]

        # Field errors keep the link usable so the user can correct their input.
        response = self.client.post(set_password_url, {
            "new_password1": "New-autumn-password-927!", "new_password2": "mismatch",
        })
        self.assertContains(response, "The two password fields")
        new_password = "New-autumn-password-927!"
        response = self.client.post(set_password_url, {
            "new_password1": new_password, "new_password2": new_password,
        })
        self.assertRedirects(response, reverse("password_reset_complete"))
        self.assertTrue(self.client.login(username=self.user.username, password=new_password))
        response = self.client.get(urlsplit(link).path, follow=True)
        self.assertFalse(response.context["validlink"])
        self.assertContains(response, "This reset link is invalid or has expired.")

    def test_smtp_failure_shows_retry_error(self):
        with patch("django.core.mail.EmailMultiAlternatives.send", side_effect=smtplib.SMTPException), self.assertLogs("main", level="ERROR"):
            response = self.client.post(reverse("password_reset"), {"email": self.user.email})

        self.assertContains(response, "Couldn't send the email right now. Try again later.", html=True)
