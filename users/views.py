from .forms import *
from .codex_auth import (
    CodexAuthError,
    CodexDevicePending,
    deserialize_token_bundle,
    poll_device_code_login,
    serialize_token_bundle,
    start_device_code_login,
    token_bundle_summary,
)
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
from .context_processors import configured_social_providers
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
def profile(request):
    if request.method == 'POST':
        profile = request.user.profile
        ai_features_enabled = profile.ai_features_enabled
        ai_action_submitted = any(
            action in request.POST
            for action in (
                'start_openai_chatgpt_login',
                'complete_openai_chatgpt_login',
                'disconnect_openai_chatgpt',
            )
        )
        if ai_action_submitted and not ai_features_enabled:
            request.session.pop('openai_chatgpt_device_code', None)
            messages.error(request, 'AI features are disabled for this account.')
            return redirect('profile')

        if 'start_openai_chatgpt_login' in request.POST:
            try:
                device_code = start_device_code_login()
            except CodexAuthError as e:
                messages.error(request, f'Could not start Codex login: {e}')
            else:
                request.session['openai_chatgpt_device_code'] = device_code.as_session_dict()
                messages.success(request, 'Codex login started. Use the code shown below, then complete the login.')
            return redirect('profile')

        if 'complete_openai_chatgpt_login' in request.POST:
            device_code = request.session.get('openai_chatgpt_device_code')
            if not device_code:
                messages.error(request, 'Start Codex login first.')
                return redirect('profile')
            try:
                bundle = poll_device_code_login(device_code)
            except CodexDevicePending:
                messages.info(request, 'Still waiting for OpenAI authorization. Try Complete again after entering the code.')
            except CodexAuthError as e:
                messages.error(request, f'Could not complete Codex login: {e}')
            else:
                profile.set_api_key('openai_chatgpt', serialize_token_bundle(bundle))
                profile.save()
                request.session.pop('openai_chatgpt_device_code', None)
                messages.success(request, 'Connected Codex login for Insights.')
            return redirect('profile')

        if 'disconnect_openai_chatgpt' in request.POST:
            profile.set_api_key('openai_chatgpt', None)
            profile.save()
            request.session.pop('openai_chatgpt_device_code', None)
            messages.success(request, 'Disconnected OpenAI Codex login.')
            return redirect('profile')

        u_form = UserUpdateForm(request.POST, instance=request.user)
        p_form = ProfileUpdateForm(request.POST, request.FILES, instance=profile)

        if u_form.is_valid() and p_form.is_valid():
            u_form.save()
            # handle automatic background image setting
            if p_form.cleaned_data.get('automatic_background'):
                background_choice = p_form.cleaned_data.get('background_choice')
                if background_choice == 'bing':
                    profile.bing_background = True
                    profile.nasa_apod_background = False
                elif background_choice == 'nasa':
                    profile.bing_background = False
                    profile.nasa_apod_background = True
                else:
                    profile.bing_background = False
                    profile.nasa_apod_background = False
            # Handle background image removal
            if p_form.cleaned_data.get('remove_background_image'):
                if profile.background_image:
                    profile.background_image.delete(save=False)
                profile.background_image = None
            # Handle API keys store/clear only when the account trait allows AI features.
            if profile.ai_features_enabled:
                if p_form.cleaned_data.get('clear_gemini_api_key'):
                    profile.set_api_key('gemini', None)
                elif p_form.cleaned_data.get('gemini_api_key'):
                    profile.set_api_key('gemini', p_form.cleaned_data.get('gemini_api_key').strip())
                if p_form.cleaned_data.get('clear_openai_api_key'):
                    profile.set_api_key('openai', None)
                elif p_form.cleaned_data.get('openai_api_key'):
                    profile.set_api_key('openai', p_form.cleaned_data.get('openai_api_key').strip())
                if p_form.cleaned_data.get('clear_claude_api_key'):
                    profile.set_api_key('claude', None)
                elif p_form.cleaned_data.get('claude_api_key'):
                    profile.set_api_key('claude', p_form.cleaned_data.get('claude_api_key').strip())
            profile.save()
            p_form.save()
            messages.success(request, f'Profile updated successfully.')
            return redirect('profile')
    else:
        u_form = UserUpdateForm(instance=request.user)
        p_form = ProfileUpdateForm(instance=request.user.profile,
                                   initial={
                                      'automatic_background': request.user.profile.automatic_background,
                                      'background_choice': 'bing' if request.user.profile.bing_background else 'nasa' if request.user.profile.nasa_apod_background else '',
                                   })
    # Provide masked info about which keys are set
    profile = request.user.profile
    ai_features_enabled = profile.ai_features_enabled
    have_keys = {
        'gemini': bool(profile.gemini_api_key_enc),
        'openai': bool(profile.openai_api_key_enc),
        'openai_chatgpt': bool(profile.openai_chatgpt_token_enc),
        'claude': bool(profile.claude_api_key_enc),
        'openai_server': bool(os.environ.get('OPENAI_API_KEY')),
    }
    have_keys['profile_credentials'] = any(
        have_keys[provider]
        for provider in ('gemini', 'openai', 'openai_chatgpt', 'claude')
    )
    have_keys['openai_available'] = have_keys['openai'] or have_keys['openai_server']
    openai_chatgpt_bundle = (
        deserialize_token_bundle(profile.get_api_key('openai_chatgpt'))
        if ai_features_enabled
        else None
    )
    social_accounts = {
        account.provider: account
        for account in SocialAccount.objects.filter(
            user=request.user,
            provider__in=('google', 'github'),
        )
    }
    social_auth_connections = []
    for provider in configured_social_providers():
        account = social_accounts.get(provider['id'])
        if not provider['enabled'] and account is None:
            continue
        connection = dict(provider)
        connection['account'] = account
        connection['display_identity'] = (
            account.extra_data.get('email')
            or account.extra_data.get('login')
            or account.uid
            if account
            else ''
        )
        social_auth_connections.append(connection)
    context = {
        'user_form': u_form,
        'profile_form': p_form,
        'ai_features_enabled': ai_features_enabled,
        'have_keys': have_keys,
        'openai_chatgpt_device_code': request.session.get('openai_chatgpt_device_code') if ai_features_enabled else None,
        'openai_chatgpt_summary': token_bundle_summary(openai_chatgpt_bundle),
        'social_auth_connections': social_auth_connections,
    }
    return render(request, 'users/profile.html', context)

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
