from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.api_v2.exceptions import V2APIView
from core.api_v2.serializers import MeSerializer


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
                "capabilities": [],
                "user": {
                    "id": request.user.id,
                    "username": request.user.username,
                    "timezone": profile_timezone,
                },
            }
        )
