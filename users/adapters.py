from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import redirect
from django.urls import reverse


class AutumnAccountAdapter(DefaultAccountAdapter):
    """Keep allauth signups aligned with Autumn's instance policy."""

    def is_open_for_signup(self, request):
        return settings.ALLOW_REGISTRATION


class AutumnSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Apply Autumn's explicit, non-merging social account policy."""

    def is_open_for_signup(self, request, sociallogin):
        return settings.ALLOW_REGISTRATION

    def get_connect_redirect_url(self, request, socialaccount):
        return reverse("profile")

    def pre_social_login(self, request, sociallogin):
        # Linked identities can log in normally. When an authenticated user is
        # connecting a provider, allauth binds it to that session's user.
        if sociallogin.is_existing or request.user.is_authenticated:
            return

        verified_emails = {
            address.email.strip()
            for address in sociallogin.email_addresses
            if address.verified and address.email
        }
        if not verified_emails:
            return

        User = get_user_model()
        email_belongs_to_local_account = any(
            User.objects.filter(email__iexact=email).exists()
            for email in verified_emails
        )
        if email_belongs_to_local_account:
            messages.info(
                request,
                "An Autumn account already uses that email. Log in with your "
                "password, then connect the provider from Profile.",
            )
            raise ImmediateHttpResponse(redirect("login"))
