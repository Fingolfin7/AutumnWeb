from django.contrib.staticfiles import finders
from django.http import FileResponse, Http404, JsonResponse
from django.templatetags.static import static
from django.views.decorators.cache import never_cache


def manifest(request):
    return JsonResponse(
        {
            "name": "Autumn",
            "short_name": "Autumn",
            "description": "Autumn is a time management application.",
            "id": "/",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#faf6ee",
            "theme_color": "#8f3f24",
            "categories": ["productivity", "utilities"],
            "icons": [
                {
                    "src": static("core/images/icons/autumn-icon-192.png"),
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "any",
                },
                {
                    "src": static("core/images/icons/autumn-icon-512.png"),
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any",
                },
                {
                    "src": static("core/images/icons/autumn-maskable-512.png"),
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "maskable",
                },
            ],
            "shortcuts": [
                {
                    "name": "Start Timer",
                    "short_name": "Start",
                    "url": "/start_timer/",
                    "icons": [
                        {
                            "src": static("core/images/icons/autumn-icon-192.png"),
                            "sizes": "192x192",
                            "type": "image/png",
                        }
                    ],
                },
                {
                    "name": "Timers",
                    "short_name": "Timers",
                    "url": "/timers/",
                    "icons": [
                        {
                            "src": static("core/images/icons/autumn-icon-192.png"),
                            "sizes": "192x192",
                            "type": "image/png",
                        }
                    ],
                },
            ],
        },
        content_type="application/manifest+json",
    )


@never_cache
def service_worker(request):
    service_worker_path = finders.find("core/pwa/service-worker.js")
    if not service_worker_path:
        raise Http404("Service worker not found")

    response = FileResponse(
        open(service_worker_path, "rb"),
        content_type="text/javascript; charset=utf-8",
    )
    response["Service-Worker-Allowed"] = "/"
    return response
