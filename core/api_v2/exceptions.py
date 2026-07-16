from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework.exceptions import (
    MethodNotAllowed,
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    Throttled,
    ValidationError,
)
from rest_framework.response import Response
from rest_framework.views import APIView


def _envelope(code, message, details=None):
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
        }
    }


def v2_exception_handler(exc, context):
    mappings = (
        (ValidationError, "validation_error", 400),
        (NotAuthenticated, "not_authenticated", 401),
        ((DjangoPermissionDenied, PermissionDenied), "permission_denied", 403),
        ((Http404, NotFound), "not_found", 404),
        (MethodNotAllowed, "method_not_allowed", 405),
        (Throttled, "throttled", 429),
    )
    for exception_type, code, status_code in mappings:
        if isinstance(exc, exception_type):
            details = None
            if isinstance(exc, ValidationError):
                details = (
                    exc.detail
                    if isinstance(exc.detail, dict)
                    else {"non_field_errors": exc.detail}
                )
            message = "Invalid input." if isinstance(exc, ValidationError) else str(
                getattr(exc, "detail", exc)
            )
            return Response(
                _envelope(code, message, details),
                status=status_code,
            )
    return None


class V2APIView(APIView):
    def get_exception_handler(self):
        return v2_exception_handler
