from .forms import *
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.views import LoginView
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse

def debug_session(request):
    return JsonResponse({
        "is_authenticated": request.user.is_authenticated,
        "user": str(request.user),
        "backend": request.session.get('_auth_user_backend'),
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
        p_form = ProfileUpdateForm(instance=request.user.profile)

    context = {
        'user_form': u_form,
        'profile_form': p_form
    }
    return render(request, 'users/profile.html', context)