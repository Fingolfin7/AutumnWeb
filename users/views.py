from .forms import *
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.views import LoginView
from django.contrib.auth.decorators import login_required
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view
from django.http import JsonResponse, HttpResponse, FileResponse
import logging
import mimetypes
import os
import requests

logger = logging.getLogger('main')

def debug_session(request):
    return JsonResponse({
        "is_authenticated": request.user.is_authenticated,
        "user": str(request.user),
        "backend": request.session.get('_auth_user_backend'),
    })

@api_view(['GET'])
def check_auth_token(request, token):
    try:
        # Retrieve the token object from the database
        token_obj = Token.objects.get(key=token)
        return JsonResponse({
            'is_valid': bool(token_obj),
            'username': token_obj.user.username,
            'email': token_obj.user.email,
        })
    except Token.DoesNotExist:
        return JsonResponse({
            'is_valid': False,
            'error': 'Invalid token'
        })


# Create your views here.
def register(request):
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



@login_required
def profile(request):
    if request.method == 'POST':
        u_form = UserUpdateForm(request.POST, instance=request.user)
        p_form = ProfileUpdateForm(request.POST, request.FILES, instance=request.user.profile)

        if u_form.is_valid() and p_form.is_valid():
            u_form.save()

            # handle automatic background image setting
            if p_form.cleaned_data.get('automatic_background'):
                profile = request.user.profile
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
                profile = request.user.profile
                if profile.background_image:
                    profile.background_image.delete(save=False) # Delete file
                profile.background_image = None

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

    context = {
        'user_form': u_form,
        'profile_form': p_form,
    }
    return render(request, 'users/profile.html', context)

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
