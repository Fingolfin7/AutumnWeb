from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone


class UserTimezoneMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        timezone.deactivate()
        try:
            if request.user.is_authenticated:
                try:
                    timezone.activate(ZoneInfo(request.user.profile.timezone))
                except (AttributeError, KeyError, ObjectDoesNotExist, ZoneInfoNotFoundError):
                    timezone.activate(ZoneInfo(settings.TIME_ZONE))
            return self.get_response(request)
        finally:
            timezone.deactivate()
