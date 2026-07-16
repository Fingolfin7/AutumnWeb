from __future__ import annotations
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from core.models import Sessions


DEPRECATION_MESSAGE = (
    "Deprecated: totals are always derived from sessions now; "
    "there is nothing to audit."
)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def audit(request):
    """Return the explicit S7 deprecation contract."""
    return Response(
        {
            "ok": True,
            "deprecated": True,
            "message": DEPRECATION_MESSAGE,
        },
        status=200,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    """Return info about the authenticated user.

    Includes active_session_count for status indicators.
    """
    u = request.user
    active_session_count = Sessions.objects.filter(
        user=u, end_time__isnull=True
    ).count()
    return Response(
        {
            "ok": True,
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "first_name": getattr(u, "first_name", "") or "",
            "last_name": getattr(u, "last_name", "") or "",
            "active_session_count": active_session_count,
        }
    )
