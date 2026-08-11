from django.conf import settings


def configured_social_providers():
    providers = (
        {
            "id": "google",
            "name": "Google",
            "icon": "fab fa-google",
            "enabled": settings.GOOGLE_AUTH_ENABLED,
        },
        {
            "id": "github",
            "name": "GitHub",
            "icon": "fab fa-github",
            "enabled": settings.GITHUB_AUTH_ENABLED,
        },
    )
    return providers


def auth_features(request):
    """Expose deployment-level authentication features to account pages."""

    social_auth_providers = [
        provider for provider in configured_social_providers() if provider["enabled"]
    ]
    return {
        "social_auth_providers": social_auth_providers,
        "social_auth_enabled": bool(social_auth_providers),
        "allow_registration": settings.ALLOW_REGISTRATION,
    }
