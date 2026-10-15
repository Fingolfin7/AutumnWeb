from .forms import UserRegisterForm
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages
from django.contrib.auth.views import LoginView
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.http import HttpResponse, FileResponse, HttpResponseBadRequest
from django.views.decorators.http import require_GET, require_POST
from allauth.socialaccount.forms import DisconnectForm
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.github import views as github_oauth_views
from allauth.socialaccount.providers.google import views as google_oauth_views
import logging
import mimetypes
import os
import requests

logger = logging.getLogger('main')

# Create your views here.
def register(request):
    if not settings.ALLOW_REGISTRATION:
        # Single-user install: registration stays closed unless explicitly
        # enabled via the ALLOW_REGISTRATION env var.
        messages.error(request, 'Registration is disabled on this server.')
        return redirect('login')
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            messages.success(request, f'Successfully created account for {form.cleaned_data.get("username")}.')
            form.save()
            return redirect('home')
        else:
            messages.error(request, 'Error creating account. Please try again.')
    else:
        form = UserRegisterForm()
    return render(request, 'users/register.html', {'form': form})


class CustomLoginView(LoginView):
    def form_invalid(self, form):
        response = super().form_invalid(form)
        messages.error(self.request, 'Invalid username or password.')
        return response

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'Login successful.')
        return response


def _social_oauth_view(request, provider, view):
    enabled_setting = {
        'google': settings.GOOGLE_AUTH_ENABLED,
        'github': settings.GITHUB_AUTH_ENABLED,
    }
    if not enabled_setting[provider]:
        messages.error(request, f'{provider.title()} sign-in is not configured.')
        return redirect('login')
    return view(request)


def google_oauth_login(request):
    return _social_oauth_view(request, 'google', google_oauth_views.oauth2_login)


def google_oauth_callback(request):
    return _social_oauth_view(request, 'google', google_oauth_views.oauth2_callback)


def github_oauth_login(request):
    return _social_oauth_view(request, 'github', github_oauth_views.oauth2_login)


def github_oauth_callback(request):
    return _social_oauth_view(request, 'github', github_oauth_views.oauth2_callback)


@require_GET
def account_login_redirect(request):
    """Send allauth fallbacks to Autumn's canonical login page."""

    return redirect('login')


@login_required
@require_POST
def disconnect_social_account(request, provider):
    if provider not in {'google', 'github'}:
        return HttpResponseBadRequest('Unsupported social account provider.')

    account = get_object_or_404(
        SocialAccount,
        user=request.user,
        provider=provider,
    )
    form = DisconnectForm(data={'account': account.pk}, request=request)
    if form.is_valid():
        form.save()
        messages.success(request, f'{provider.title()} account disconnected.')
    else:
        error = next(
            (message for errors in form.errors.values() for message in errors),
            f'{provider.title()} could not be disconnected.',
        )
        messages.error(request, error)
    return redirect('profile')



@login_required
@require_POST
def set_background_dimming(request):
    """Persist the header's backdrop-dimming slider.

    The slider lives in the app header, so it fires on every drag. It writes
    one integer and returns no body: the page has already applied the value to
    --background-dim-opacity locally, and this is only catching up the server
    so the choice survives a reload and follows the user to another device.

    Clamped to the same 0-85 the profile form enforces rather than trusted,
    and saved with update_fields so a rapid drag cannot race the rest of the
    profile out from under a form the user may have open in another tab.
    """
    try:
        value = int(request.POST.get("value", ""))
    except (TypeError, ValueError):
        return HttpResponseBadRequest("value must be an integer")

    profile = request.user.profile
    profile.background_dimming = max(0, min(85, value))
    profile.save(update_fields=["background_dimming"])
    return HttpResponse(status=204)


@login_required
def download_background(request):
    """Force download of the user's current background image (automatic or manual)."""
    profile = request.user.profile

    # Automatic background sources
    if profile.automatic_background:
        from core.templatetags.background_images import (
            bing_background,
            nasa_apod_background,
            bing_background_title,
            nasa_apod_title,
        )
        if profile.bing_background:
            url = bing_background()
            title = bing_background_title() or 'bing_daily'
        elif profile.nasa_apod_background:
            url = nasa_apod_background()
            title = nasa_apod_title() or 'nasa_apod'
        else:
            messages.error(request, 'No automatic background source selected.')
            return redirect('profile')

        if not url:
            messages.error(request, 'No automatic background image available right now.')
            return redirect('profile')

        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            content_type = resp.headers.get('Content-Type') or mimetypes.guess_type(url)[0] or 'application/octet-stream'
            ext = mimetypes.guess_extension(content_type) or '.jpg'
            filename = f"{title}{ext}".replace(' ', '_')
            response = HttpResponse(resp.content, content_type=content_type)
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response
        except Exception as e:
            logger.error('Failed to fetch automatic background for download: %s', e)
            messages.error(request, 'Failed to download automatic background image.')
            return redirect('profile')

    # Manual uploaded background
    if profile.background_image:
        try:
            file_field = profile.background_image
            filename = os.path.basename(file_field.name)
            return FileResponse(file_field.open('rb'), as_attachment=True, filename=filename)
        except Exception as e:
            logger.error('Failed to open manual background for download: %s', e)
            messages.error(request, 'Failed to download background image.')
            return redirect('profile')

    messages.error(request, 'No background image to download.')
    return redirect('profile')
