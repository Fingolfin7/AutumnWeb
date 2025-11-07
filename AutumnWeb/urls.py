"""
URL configuration for AutumnWeb project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include, reverse_lazy
from django.contrib.auth import views as auth_views
from rest_framework.authtoken.views import obtain_auth_token
from users import views as user_views
from users.forms import UserLoginForm




urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
    path('get-auth-token/', obtain_auth_token, name='get-auth-token'),
    path('check-auth-token/<token>/', user_views.check_auth_token, name='check-auth-token'),
    path("debug-session/", user_views.debug_session, name="debug_session"),
    path('insights/', include('llm_insights.urls')),
    path('register/', user_views.register, name='register'),
    path('login/', user_views.CustomLoginView.as_view(template_name='users/login.html',
                                                 authentication_form=UserLoginForm), name='login'),
    path('logout/', auth_views.LogoutView.as_view(template_name='users/logout.html'), name='logout'),
    path('profile/', user_views.profile, name='profile'),
    path('profile/download-background/', user_views.download_background, name='download_background'),

    path('password-reset/', auth_views.PasswordResetView.as_view(template_name='users/password_reset.html',
                                                                     html_email_template_name='users/Email Password Reset Template.html',
                                                                     subject_template_name='users/password_reset_subject.txt',
             success_url=reverse_lazy('login')),
             name='password_reset'),
    # ref: https://docs.djangoproject.com/en/3.0/topics/auth/default/#django.contrib.auth.views.PasswordResetView

    # path('password-reset/done/ ',
    #      auth_views.PasswordResetDoneView.as_view(template_name='users/password_reset_done.html'),
    #      name='password_reset_done'),
    #
    # path('password-reset/confirm/<uidb64>/<token>/',
    #      auth_views.PasswordResetConfirmView.as_view(template_name='users/password_reset_confirm.html'),
    #      name='password_reset_confirm'),
    #
    # path('password-reset/complete/',
    #      auth_views.PasswordResetCompleteView.as_view(template_name='users/Email Password Reset Template.html'),
    #      name='password_reset_complete'),


]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)