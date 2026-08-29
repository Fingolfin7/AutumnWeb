"""Authenticated, same-origin endpoints used by the browser push UI."""

from __future__ import annotations

import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from core.models import PushSubscription, TimerReminder
from core.services.push import (
    PushValidationError,
    enqueue_push_test,
    disable_subscription,
    push_configured,
    save_subscription,
    validate_endpoint,
)


def _json_body(request):
    if len(request.body) > 32 * 1024:
        raise PushValidationError("Request body is too large.")
    try:
        value = json.loads(request.body.decode("utf-8")) if request.body else {}
    except (UnicodeDecodeError, TypeError, ValueError):
        raise PushValidationError("Request body must be valid JSON.") from None
    if not isinstance(value, dict):
        raise PushValidationError("Request body must be a JSON object.")
    return value


@login_required
@require_GET
def push_status(request):
    active = PushSubscription.objects.filter(user=request.user, active=True).count()
    return JsonResponse(
        {
            "available": push_configured(),
            # Only the public VAPID key is safe to send to the browser.
            "public_key": settings.PUSH_VAPID_PUBLIC_KEY if push_configured() else None,
            "subscriptions": active,
            "subscribed": active > 0,
        }
    )


@login_required
@require_POST
@csrf_protect
def push_subscribe(request):
    try:
        subscription = save_subscription(user=request.user, payload=_json_body(request))
    except PushValidationError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(
        {"id": subscription.pk, "active": subscription.active}, status=201
    )


@login_required
@require_POST
@csrf_protect
def push_unsubscribe(request):
    try:
        payload = _json_body(request)
        endpoint = validate_endpoint(payload.get("endpoint"))
        subscription = disable_subscription(user=request.user, endpoint=endpoint)
    except PushValidationError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"removed": subscription is not None})


@login_required
@require_POST
@csrf_protect
def push_test(request):
    """Queue a fixed diagnostic event for this account's active devices.

    The request intentionally accepts no endpoint, payload, or recipient
    selector.  The dispatcher performs the provider call later, so this view
    cannot be used to probe arbitrary URLs or expose VAPID private material.
    """

    try:
        body = _json_body(request)
    except PushValidationError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    if body:
        return JsonResponse(
            {"error": "Push test accepts an empty JSON object only."}, status=400
        )
    event = enqueue_push_test(user=request.user)
    return JsonResponse(
        {"queued": True, "event_id": event.pk}, status=202
    )


@login_required
@require_POST
@csrf_protect
def cancel_timer_reminder(request, session_id: int, reminder_id: int):
    """Cancel one active reminder after checking session and user ownership."""

    with transaction.atomic():
        reminder = (
            TimerReminder.objects.select_for_update()
            .filter(
                pk=reminder_id,
                session_id=session_id,
                session__user=request.user,
                active=True,
            )
            .first()
        )
        if reminder is None:
            return JsonResponse({"cancelled": False}, status=404)
        reminder.active = False
        reminder.next_fire_at = None
        reminder.cancelled_at = timezone.now().replace(microsecond=0)
        reminder.save(update_fields=["active", "next_fire_at", "cancelled_at"])
    return JsonResponse({"cancelled": True})
