"""Web Push subscription storage and durable outbox delivery.

The request handlers in :mod:`core.views.push` only write subscriptions and
notification events.  A dispatcher calls :func:`flush_outbox` after those
transactions commit; no provider request is made while a web request holds a
database transaction.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import logging
from datetime import datetime, timedelta, timezone as dt_timezone
from urllib.parse import urlsplit
from uuid import uuid4

from django.conf import settings
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import F, Q
from django.utils import timezone

from core.models import NotificationDelivery, NotificationEvent, PushSubscription

try:  # Keep imports useful for migrations and environments before install.
    from pywebpush import WebPushException, webpush
except ImportError:  # pragma: no cover - requirements install supplies this
    webpush = None

    class WebPushException(Exception):
        response = None


logger = logging.getLogger(__name__)

MAX_ENDPOINT_LENGTH = 2048
MAX_SUBSCRIPTION_BODY_BYTES = 32 * 1024
MAX_PAYLOAD_BYTES = 4096
MAX_DELIVERIES_PER_PASS = 100
MAX_ERROR_LENGTH = 500
MAX_NOTIFICATION_TITLE_LENGTH = 120
MAX_NOTIFICATION_BODY_LENGTH = 500
MAX_NOTIFICATION_URL_LENGTH = 1024


class PushValidationError(ValueError):
    """Client supplied an invalid subscription payload."""


class PushUnavailable(RuntimeError):
    """The deployment cannot send push at this time."""


def push_configured() -> bool:
    """Return whether all VAPID values needed by pywebpush are present."""

    return bool(
        getattr(settings, "PUSH_VAPID_PUBLIC_KEY", "")
        and getattr(settings, "PUSH_VAPID_PRIVATE_KEY", "")
        and getattr(settings, "PUSH_VAPID_SUBJECT", "")
    )


def _decode_key(value: object, *, name: str) -> bytes:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise PushValidationError(f"Subscription key {name} is invalid.")
    try:
        # Validate the alphabet as well as padding.  urlsafe_b64decode silently
        # ignores several malformed characters otherwise.
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
    except (binascii.Error, ValueError, TypeError):
        raise PushValidationError(f"Subscription key {name} is invalid.") from None
    if name == "p256dh" and len(decoded) != 65:
        raise PushValidationError("Subscription p256dh key is invalid.")
    if name == "auth" and not 8 <= len(decoded) <= 64:
        raise PushValidationError("Subscription auth key is invalid.")
    return decoded


def validate_endpoint(endpoint: object) -> str:
    """Validate a browser endpoint before storing or disabling it.

    The unsubscribe endpoint does not carry keys, so it uses this narrower
    validator.  Rejecting local and private IP literals prevents this feature
    from becoming an accidental server-side request primitive.  DNS lookup is
    intentionally not performed during a request: provider hosts can be
    temporarily unresolvable and endpoint registration must remain local.
    """

    if not isinstance(endpoint, str) or not endpoint or len(endpoint) > MAX_ENDPOINT_LENGTH:
        raise PushValidationError("Subscription endpoint is invalid.")
    parts = urlsplit(endpoint)
    try:
        port = parts.port
    except ValueError:
        raise PushValidationError("Subscription endpoint must be an HTTPS URL.") from None
    if (
        parts.scheme.lower() != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.fragment
        or port not in (None, 443)
    ):
        raise PushValidationError("Subscription endpoint must be an HTTPS URL.")
    hostname = parts.hostname.rstrip(".").lower()
    if hostname in {"localhost", "localhost.localdomain"}:
        raise PushValidationError("Subscription endpoint host is invalid.")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    ):
        raise PushValidationError("Subscription endpoint host is invalid.")
    allowed_suffixes = getattr(settings, "PUSH_ALLOWED_ENDPOINT_SUFFIXES", ())
    if not any(
        hostname == suffix or hostname.endswith(f".{suffix}")
        for suffix in allowed_suffixes
    ):
        raise PushValidationError("Subscription endpoint provider is not allowed.")
    return endpoint


def _expiration_time(value: object):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise PushValidationError("Subscription expiration time is invalid.")
    try:
        # The browser API exposes expirationTime as epoch milliseconds.
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        result = datetime.fromtimestamp(timestamp, tz=dt_timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        raise PushValidationError("Subscription expiration time is invalid.") from None
    return result


def validate_subscription(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise PushValidationError("Subscription must be a JSON object.")
    endpoint = validate_endpoint(payload.get("endpoint"))
    keys = payload.get("keys")
    if not isinstance(keys, dict):
        raise PushValidationError("Subscription keys are required.")
    _decode_key(keys.get("p256dh"), name="p256dh")
    _decode_key(keys.get("auth"), name="auth")
    return {
        "endpoint": endpoint,
        "p256dh": keys["p256dh"],
        "auth": keys["auth"],
        "expiration_time": _expiration_time(payload.get("expirationTime")),
    }


def _cancel_pending_deliveries(subscription, *, reason: str) -> None:
    """Stop old-user notifications crossing an endpoint ownership change."""

    NotificationDelivery.objects.filter(
        subscription=subscription, status__in=("pending", "processing")
    ).update(
        status="unavailable",
        lease_until=None,
        last_error=reason[:MAX_ERROR_LENGTH],
        last_error_at=timezone.now(),
    )


def save_subscription(*, user, payload: object):
    """Create or transfer a globally unique endpoint to ``user``."""

    data = validate_subscription(payload)
    # The nested savepoint makes a uniqueness race recoverable on both SQLite
    # and PostgreSQL.  The endpoint is then locked before its owner changes.
    for attempt in range(2):
        try:
            with transaction.atomic():
                subscription = (
                    PushSubscription.objects.select_for_update()
                    .filter(endpoint=data["endpoint"])
                    .first()
                )
                if subscription is None:
                    try:
                        with transaction.atomic():
                            subscription = PushSubscription.objects.create(
                                user=user,
                                endpoint=data["endpoint"],
                                p256dh=data["p256dh"],
                                auth=data["auth"],
                                expiration_time=data["expiration_time"],
                                active=True,
                            )
                    except IntegrityError:
                        subscription = PushSubscription.objects.select_for_update().get(
                            endpoint=data["endpoint"]
                        )

                changed_owner = subscription.user_id != user.id
                if changed_owner:
                    _cancel_pending_deliveries(
                        subscription, reason="Subscription endpoint ownership transferred"
                    )
                    subscription.user = user
                subscription.p256dh = data["p256dh"]
                subscription.auth = data["auth"]
                subscription.expiration_time = data["expiration_time"]
                subscription.active = True
                subscription.disabled_at = None
                subscription.last_error = ""
                subscription.save(
                    update_fields=[
                        "user",
                        "p256dh",
                        "auth",
                        "expiration_time",
                        "active",
                        "disabled_at",
                        "last_error",
                        "updated_at",
                    ]
                )
                return subscription
        except IntegrityError:
            if attempt == 1:
                raise
    raise AssertionError("unreachable")


@transaction.atomic
def disable_subscription(*, user, endpoint: str):
    endpoint = validate_endpoint(endpoint)
    subscription = (
        PushSubscription.objects.select_for_update()
        .filter(user=user, endpoint=endpoint)
        .first()
    )
    if subscription is not None and subscription.active:
        now = timezone.now()
        subscription.active = False
        subscription.disabled_at = now
        subscription.save(update_fields=["active", "disabled_at", "updated_at"])
        _cancel_pending_deliveries(subscription, reason="Subscription disabled by user")
    return subscription


def _response_status(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status is None:
        status = getattr(response, "status", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _safe_error(exc: BaseException) -> str:
    # Provider exceptions can contain an endpoint URL; retain only a bounded
    # diagnostic for operators and never put it in a browser response.
    value = str(exc).replace("\r", " ").replace("\n", " ").strip()
    return (value or exc.__class__.__name__)[:MAX_ERROR_LENGTH]


def _event_terminal_status(event, status: str, *, error: str | None = None):
    now = timezone.now()
    fields = {"status": status, "delivered_at": now if status == "delivered" else None}
    if error is not None:
        fields.update(last_error=error[:MAX_ERROR_LENGTH], last_error_at=now)
    else:
        fields.update(last_error="", last_error_at=None)
    NotificationEvent.objects.filter(pk=event.pk, status="pending").update(**fields)


def _serialize_payload(payload: object) -> str:
    # Keep the fields understood by the service worker and bound user text.
    # Web Push encryption adds framing bytes, so MAX_PAYLOAD_BYTES remains a
    # conservative ceiling rather than allowing an unbounded event payload to
    # turn into a provider-side permanent failure.
    if isinstance(payload, dict):
        payload = {
            key: payload[key]
            for key in (
                "title",
                "body",
                "url",
                "kind",
                "session_id",
                "session_uuid",
                "reminder_id",
                "scheduled_at",
            )
            if key in payload
        }
        for key, length in (
            ("title", MAX_NOTIFICATION_TITLE_LENGTH),
            ("body", MAX_NOTIFICATION_BODY_LENGTH),
            ("url", MAX_NOTIFICATION_URL_LENGTH),
        ):
            if key in payload and not isinstance(payload[key], str):
                payload[key] = str(payload[key])
            if key in payload:
                payload[key] = payload[key][:length]
    try:
        value = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise PushValidationError("Notification payload is not JSON serializable.") from exc
    if len(value.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        if isinstance(payload, dict) and isinstance(payload.get("body"), str):
            body = payload["body"]
            # Unicode characters may occupy more than one byte, so converge
            # by bytes rather than assuming one character equals one byte.
            while body and len(value.encode("utf-8")) > MAX_PAYLOAD_BYTES:
                body = body[: max(0, len(body) // 2)]
                payload["body"] = body
                value = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        if len(value.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            # Retain a valid, bounded notification even for an arbitrary
            # caller-supplied payload containing huge nested values.
            value = json.dumps(
                {"title": "Autumn", "body": "Your timer notification is ready."},
                separators=(",", ":"),
            )
    return value


def send_push(subscription, payload: object, *, ttl: int = 300):
    """Perform the one external network call used by the dispatcher."""

    if not push_configured() or webpush is None:
        raise PushUnavailable("Web Push is not configured.")
    return webpush(
        subscription_info={
            "endpoint": subscription.endpoint,
            "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
        },
        data=_serialize_payload(payload),
        vapid_private_key=settings.PUSH_VAPID_PRIVATE_KEY,
        vapid_claims={"sub": settings.PUSH_VAPID_SUBJECT},
        ttl=ttl,
        timeout=getattr(settings, "PUSH_WEBPUSH_TIMEOUT", 10.0),
    )


@transaction.atomic
def enqueue_push_test(*, user):
    """Queue a fixed diagnostic event; delivery happens in the dispatcher."""

    now = timezone.now().replace(microsecond=0)
    return NotificationEvent.objects.create(
        dedupe_key=f"push-test:{user.pk}:{uuid4()}",
        event_type="reminder",  # model v1 has reminder and auto_stop types
        user=user,
        payload={
            "title": "Autumn test notification",
            "body": "Web Push is working.",
            "url": "/timers/",
            "kind": "test",
        },
        scheduled_at=now,
    )


def _retry_delay(attempts: int) -> timedelta:
    base = max(1, int(getattr(settings, "PUSH_RETRY_BASE_SECONDS", 30)))
    return timedelta(seconds=min(base * (2 ** max(0, attempts - 1)), 3600))


def _claim_delivery(delivery_id: int, *, now):
    """Claim one delivery with a short, portable per-device CAS lease.

    A conditional update is used instead of ``skip_locked`` (which SQLite
    does not implement).  The database itself decides which concurrent caller
    won the pending/stale predicate; the network call starts only after this
    transaction commits.
    """

    lease_until = now + timedelta(
        seconds=max(1, int(getattr(settings, "PUSH_CLAIM_LEASE_SECONDS", 120)))
    )
    try:
        with transaction.atomic():
            due = Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now)
            stale = Q(lease_until__isnull=True) | Q(lease_until__lte=now)
            claimed = NotificationDelivery.objects.filter(pk=delivery_id).filter(
                (Q(status="pending") & due) | (Q(status="processing") & stale)
            ).update(
                status="processing",
                lease_until=lease_until,
                attempts=F("attempts") + 1,
            )
            if not claimed:
                return None
            return NotificationDelivery.objects.select_related("subscription").get(
                pk=delivery_id
            )
    except OperationalError as exc:
        # SQLite can report a short-lived write lock under two local workers.
        # The other caller owns the lease; skipping this candidate is safe and
        # the next bounded pass will retry it if it remains due.
        if "locked" in str(exc).lower():
            return None
        raise


def _fanout_event(event):
    """Add one pending delivery for every currently active subscription."""

    active = list(PushSubscription.objects.filter(user_id=event.user_id, active=True))
    rows = [
        NotificationDelivery(event=event, subscription=subscription, status="pending")
        for subscription in active
    ]
    if rows:
        NotificationDelivery.objects.bulk_create(rows, ignore_conflicts=True)
    return NotificationDelivery.objects.filter(event=event).exists()


def _event_state(event):
    deliveries = list(
        NotificationDelivery.objects.filter(event=event).values_list(
            "status", "last_error"
        )
    )
    if not deliveries:
        return "unavailable", "No active subscriptions"
    statuses = {status for status, _ in deliveries}
    if statuses & {"pending", "processing"}:
        return "pending", None
    if "delivered" in statuses:
        return "delivered", None
    if statuses <= {"unavailable", "expired"}:
        return "unavailable", "No active subscriptions could receive this notification"
    errors = [error for status, error in deliveries if status == "failed" and error]
    return "failed", (errors[0] if errors else "All push deliveries failed")


def dispatch_event(event_id: int, *, now=None) -> str:
    """Fan out and deliver one pending event without holding locks on I/O."""

    now = now or timezone.now()
    try:
        event = NotificationEvent.objects.get(pk=event_id)
    except NotificationEvent.DoesNotExist:
        return "missing"
    if event.status != "pending":
        return event.status
    if not push_configured():
        _event_terminal_status(event, "unavailable", error="VAPID is not configured")
        return "unavailable"

    with transaction.atomic():
        event = NotificationEvent.objects.select_for_update().get(pk=event.pk)
        if event.status != "pending":
            return event.status
        has_deliveries = _fanout_event(event)
        if not has_deliveries:
            _event_terminal_status(event, "unavailable", error="No active subscriptions")
            return "unavailable"

    due_filter = Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now)
    stale_filter = Q(lease_until__isnull=True) | Q(lease_until__lte=now)
    deliveries = list(
        NotificationDelivery.objects.filter(event=event)
        .filter(
            (Q(status="pending") & due_filter)
            | (Q(status="processing") & stale_filter)
        )
        .select_related("subscription")
        .order_by("id")[:MAX_DELIVERIES_PER_PASS]
    )
    for candidate in deliveries:
        delivery = _claim_delivery(candidate.pk, now=now)
        if delivery is None:
            continue
        try:
            # The transaction opened by _claim_delivery has committed here.
            send_push(delivery.subscription, event.payload)
        except PushUnavailable as exc:
            NotificationDelivery.objects.filter(pk=delivery.pk).update(
                status="unavailable",
                last_error=_safe_error(exc),
                last_error_at=timezone.now(),
                lease_until=None,
                next_attempt_at=None,
            )
        except Exception as exc:  # Provider/network errors stay per-device.
            code = _response_status(exc)
            attempts = delivery.attempts or 0
            max_attempts = max(1, int(getattr(settings, "PUSH_MAX_ATTEMPTS", 5)))
            # 429 is a provider throttle and should back off; all other 4xx
            # responses are terminal, including malformed/auth requests.
            transient = code is None or code in (408, 425, 429) or code >= 500
            if code in (404, 410):
                status = "expired"
                PushSubscription.objects.filter(pk=delivery.subscription_id).update(
                    active=False,
                    disabled_at=timezone.now(),
                    last_error=f"Push provider returned {code}",
                    updated_at=timezone.now(),
                )
            elif transient and attempts < max_attempts:
                status = "pending"
            else:
                status = "failed"
            values = {
                "status": status,
                "next_attempt_at": now + _retry_delay(attempts)
                if status == "pending"
                else None,
                "last_error": _safe_error(exc),
                "last_error_at": timezone.now(),
                "lease_until": None,
            }
            NotificationDelivery.objects.filter(pk=delivery.pk).update(**values)
        else:
            NotificationDelivery.objects.filter(pk=delivery.pk).update(
                status="delivered",
                delivered_at=timezone.now(),
                lease_until=None,
                next_attempt_at=None,
                last_error="",
                last_error_at=None,
            )

    status, error = _event_state(event)
    if status != "pending":
        _event_terminal_status(event, status, error=error)
    return status


def flush_outbox(*, limit: int = 100, now=None) -> int:
    """Dispatch up to ``limit`` pending events and return events inspected."""

    if limit < 1:
        return 0
    now = now or timezone.now()
    event_ids = list(
        NotificationEvent.objects.filter(status="pending")
        .order_by("created_at", "id")
        .values_list("id", flat=True)[:limit]
    )
    for event_id in event_ids:
        dispatch_event(event_id, now=now)
    return len(event_ids)
