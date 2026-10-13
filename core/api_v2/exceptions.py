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


RELATED_HEADER = "X-Autumn-Related"
SIMILARITY_HEADER = "X-Autumn-Related-Similarity"


def related_outcome(request):
    """The request's RelatedOutcome, reported back in the X-Autumn-Related header."""
    from core.services.semantic_search import RelatedOutcome

    outcome = getattr(request, "_related_outcome", None)
    if outcome is None:
        outcome = request._related_outcome = RelatedOutcome()
    return outcome


class V2APIView(APIView):
    def get_exception_handler(self):
        return v2_exception_handler

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        # With search + related=true: "included", or "unavailable" when the
        # result is keyword-only (no key, AI off, nothing embedded yet, or
        # the provider failing).
        outcome = getattr(request, "_related_outcome", None)
        if outcome is not None and outcome.requested and response.status_code < 400:
            response[RELATED_HEADER] = "unavailable" if outcome.unavailable else "included"
            # The similarity cutoff the related matches were held to.
            if outcome.cutoff is not None:
                response[SIMILARITY_HEADER] = f"{outcome.cutoff:.2f}"
        return response
