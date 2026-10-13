from .base import *
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


