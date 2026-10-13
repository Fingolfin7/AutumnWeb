from .base import *

from core.templatetags.background_images import bing_background, nasa_apod_media
from core.utils import ACTIVE_CONTEXT_SESSION_KEY


def _background_payload(profile):
    if profile.background_image and not profile.automatic_background:
        try:
            image_url = profile.background_image.url
        except Exception:
            image_url = None
        return {
            "mode": "upload",
            "image_url": image_url,
            "video_url": None,
        }
    if profile.automatic_background and profile.bing_background:
        return {
            "mode": "bing",
            "image_url": bing_background() or None,
            "video_url": None,
        }
    if profile.automatic_background and profile.nasa_apod_background:
        media = nasa_apod_media()
        return {
            "mode": "apod",
            "image_url": media.get("image_url") or None,
            "video_url": media.get("video_url") or None,
        }
    return {"mode": "none", "image_url": None, "video_url": None}


def _preferences_payload(user):
    profile = user.profile
    return {
        "timezone": profile.timezone,
        "default_filter_value": profile.default_filter_value,
        "default_filter_unit": profile.default_filter_unit,
        "insights_default_filter_value": profile.insights_default_filter_value,
        "insights_default_filter_unit": profile.insights_default_filter_unit,
        "default_chart_project_count": profile.default_chart_project_count,
        "background_dimming": profile.background_dimming,
        "automatic_background": profile.automatic_background,
        "bing_background": profile.bing_background,
        "nasa_apod_background": profile.nasa_apod_background,
        "luna_recommendation_effort": profile.luna_recommendation_effort,
        "ai_features_enabled": profile.ai_features_enabled,
        "active_context_id": profile.active_context_id,
        "insights_access_enabled": profile.insights_access_enabled,
        "avatar_url": profile.image_url,
        "background": _background_payload(profile),
        "configured_api_keys": {
            "gemini": bool(profile.gemini_api_key_enc),
            "openai": bool(profile.openai_api_key_enc),
            "openai_chatgpt": bool(profile.openai_chatgpt_token_enc),
            "claude": bool(profile.claude_api_key_enc),
        },
        "contexts": [
            {"id": context.pk, "name": context.name, "color": None}
            for context in Context.objects.filter(user=user).order_by("name", "id")
        ],
    }


class MeView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=MeSerializer)
    def get(self, request):
        try:
            profile_timezone = request.user.profile.timezone
            ZoneInfo(profile_timezone)
        except (AttributeError, KeyError, ObjectDoesNotExist, ZoneInfoNotFoundError):
            profile_timezone = settings.TIME_ZONE
        return Response(
            {
                "api_version": 2,
                "capabilities": [
                    "timers",
                    "sessions",
                    "projects",
                    "subprojects",
                    "contexts",
                    "tags",
                    "reports",
                    "commitments",
                    "export",
                    "import",
                ],
                "user": {
                    "id": request.user.id,
                    "username": request.user.username,
                    "email": request.user.email,
                    "timezone": profile_timezone,
                },
            }
        )


class PreferencesView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=PreferencesResponseSerializer)
    def get(self, request):
        return Response(_preferences_payload(request.user))

    @extend_schema(
        request=PreferencesRequestSerializer,
        responses={200: PreferencesResponseSerializer},
    )
    def patch(self, request):
        serializer = PreferencesRequestSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        profile = request.user.profile

        bing = data.get("bing_background", profile.bing_background)
        apod = data.get("nasa_apod_background", profile.nasa_apod_background)
        if bing and apod:
            raise ValidationError(
                {"background": ["Bing and NASA APOD cannot both be enabled."]}
            )

        active_context = profile.active_context
        if "active_context_id" in data:
            context_id = data.pop("active_context_id")
            if context_id is None:
                active_context = None
            else:
                try:
                    active_context = Context.objects.get(
                        user=request.user, pk=context_id
                    )
                except Context.DoesNotExist as exc:
                    raise ValidationError(
                        {"active_context_id": ["Context does not belong to this user."]}
                    ) from exc

        previous_timezone = profile.timezone
        for field, value in data.items():
            setattr(profile, field, value)
        profile.active_context = active_context
        update_fields = [*data.keys(), "active_context"]
        profile.save(update_fields=update_fields)
        request.session[ACTIVE_CONTEXT_SESSION_KEY] = (
            str(active_context.pk) if active_context is not None else "all"
        )

        if profile.timezone != previous_timezone:
            from core.models import NotificationPreference
            from core.services.proactive_notifications import (
                reschedule_notification_preferences,
            )

            preference = NotificationPreference.objects.filter(
                user=request.user
            ).first()
            if preference is not None:
                reschedule_notification_preferences(preference)
        return Response(_preferences_payload(request.user))


