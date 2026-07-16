from django.http import JsonResponse

from core.api_v2.exceptions import _envelope


class V2ErrorEnvelopeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not request.path_info.startswith("/api/v2/"):
            return response
        if response.status_code == 404:
            return JsonResponse(
                _envelope("not_found", "Not found."),
                status=404,
            )
        if response.status_code == 405:
            return JsonResponse(
                _envelope("method_not_allowed", "Method not allowed."),
                status=405,
            )
        return response
