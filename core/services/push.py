"""Web Push subscription storage and durable outbox delivery.

The request handlers in :mod:`core.views.push` only write subscriptions and
notification events.  A dispatcher calls :func:`flush_outbox` after those
transactions commit; no provider request is made while a web request holds a
database transaction.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import json
import logging
import os
import re
from collections import Counter
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


try:  # Same guard: the private key is only validated when py_vapid is present.
    from py_vapid import Vapid
except ImportError:  # pragma: no cover - requirements install supplies this
    Vapid = None


logger = logging.getLogger(__name__)

MAX_ENDPOINT_LENGTH = 2048
MAX_SUBSCRIPTION_BODY_BYTES = 32 * 1024
MAX_PAYLOAD_BYTES = 4096
MAX_DELIVERIES_PER_PASS = 100
MAX_ERROR_LENGTH = 500
MAX_NOTIFICATION_TITLE_LENGTH = 120
MAX_NOTIFICATION_BODY_LENGTH = 500
MAX_NOTIFICATION_URL_LENGTH = 1024
MAX_NOTIFICATION_ACTIONS = 2
MAX_NOTIFICATION_ACTION_LABEL_LENGTH = 64
MAX_NOTIFICATION_ACTION_ID_LENGTH = 64
MAX_NOTIFICATION_TAG_LENGTH = 120
MAX_NOTIFICATION_IDENTITY_LENGTH = 120
# Keep this list deliberately narrower than "any same-origin path".  Push
# payloads can be replayed after a deployment, so a future route must be
# explicitly added here before it can become a notification destination.
NOTIFICATION_ALLOWED_PATH_PREFIXES = (
    "/timers",
    "/start_timer",
    "/notifications",
    "/commitments",
    "/update_commitment",
    "/review/weekly",
)
VAPID_CLI_PREFIX = "Application Server Key ="

_NOTIFICATION_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:+-]*$")


class PushValidationError(ValueError):
    """Client supplied an invalid subscription payload."""


class PushUnavailable(RuntimeError):
    """The deployment cannot send push at this time."""


def _normalise_vapid_public_key(value: object) -> str:
    """Return canonical unpadded base64url from the configured value.

    ``python -m py_vapid --applicationServerKey`` prints
    ``Application Server Key = <key>``.  Copying that whole line into an
    environment variable used to make the browser fail inside ``atob`` after
    notification permission had already been granted.  Standard base64 and
    padded keys decode server side but are rejected by the browser's stricter
    base64url check, so the alphabet and padding are canonicalised here too.
    """

    if not isinstance(value, str):
        return ""
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        return ""
    labelled = [line for line in lines if line.startswith(VAPID_CLI_PREFIX)]
    candidate = labelled[0][len(VAPID_CLI_PREFIX) :] if labelled else lines[0]
    candidate = candidate.strip().rstrip("=")
    return candidate.replace("+", "-").replace("/", "_")


def _private_key_loads(private_key: object) -> bool:
    """Load the private key the way ``pywebpush`` will at send time.

    ``pywebpush`` dispatches on ``os.path.isfile``, and ``Vapid.from_string``
    strips newlines without stripping PEM armour, so raw PEM contents pasted
    into the environment variable only fail once a notification is being sent.
    """

    if Vapid is None:  # pragma: no cover - requirements install supplies this
        return True
    try:
        if os.path.isfile(private_key):
            Vapid.from_file(private_key)
        else:
            Vapid.from_string(private_key)
    except Exception:
        return False
    return True


def _valid_vapid_subject(subject: str) -> bool:
    """Apply the same rules as ``py_vapid._check_sub``.

    That pattern is anchored, so a contact URI carrying a path or an address
    without a host is only rejected while signing, long after the browser has
    been told push is available.
    """

    parts = urlsplit(subject)
    if parts.scheme == "mailto":
        address = parts.path
        if "@" not in address:
            return False
        host = address.rsplit("@", 1)[1]
    elif parts.scheme == "https":
        if parts.path or parts.query or parts.fragment:
            return False
        host = parts.hostname or ""
    else:
        return False
    host = host.lower()
    return host == "localhost" or "." in host.strip(".")


def vapid_configuration() -> dict[str, object]:
    """Return validated, browser-safe VAPID configuration metadata."""

    public_key = _normalise_vapid_public_key(
        getattr(settings, "PUSH_VAPID_PUBLIC_KEY", "")
    )
    private_key = getattr(settings, "PUSH_VAPID_PRIVATE_KEY", "")
    subject = getattr(settings, "PUSH_VAPID_SUBJECT", "")
    if not public_key or not private_key or not subject:
        return {
            "configured": False,
            "public_key": None,
            "error": "Browser push credentials are incomplete.",
        }
    try:
        decoded = base64.b64decode(
            public_key + "=" * (-len(public_key) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError, TypeError):
        decoded = b""
    if len(decoded) != 65 or decoded[:1] != b"\x04":
        return {
            "configured": False,
            "public_key": None,
            "error": (
                "PUSH_VAPID_PUBLIC_KEY must be the base64url application "
                "server key, without unrelated command output."
            ),
        }
    if not _private_key_loads(private_key):
        return {
            "configured": False,
            "public_key": None,
            "error": (
                "PUSH_VAPID_PRIVATE_KEY must be a path to the PEM file or the "
                "base64url DER key (not raw PEM contents)."
            ),
        }
    if not _valid_vapid_subject(str(subject)):
        return {
            "configured": False,
            "public_key": None,
            "error": (
                "PUSH_VAPID_SUBJECT must be a mailto: address or an https: "
                "origin without a path."
            ),
        }
    return {"configured": True, "public_key": public_key, "error": None}


def push_configured() -> bool:
    """Return whether all VAPID values needed by pywebpush are valid."""

    return bool(vapid_configuration()["configured"])


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


def _allowed_notification_path(path: str) -> bool:
    """Return whether *path* is an explicitly supported Autumn route."""

    # Do not let a browser URL parser turn a backslash or dot segment into a
    # different path after validation.  Fragments and query strings are fine,
    # including the timer hash used by the existing reminder events.
    # Empty components are normal for a trailing slash, but dot segments and
    # backslashes are rejected because browser URL parsers canonicalise them.
    if (
        "\\" in path
        or re.search(r"%(?:2e|2f|5c)", path, flags=re.IGNORECASE)
        or any(part in {".", ".."} for part in path.split("/"))
    ):
        return False
    return any(
        path == prefix or path.startswith(f"{prefix}/")
        for prefix in NOTIFICATION_ALLOWED_PATH_PREFIXES
    )


def validate_notification_url(value: object, *, default: str = "/timers/") -> str:
    """Validate a same-origin, relative notification destination.

    Notification destinations are data supplied by claimers and eventually
    interpreted by a service worker.  Requiring an absolute-root relative
    URL, rejecting credentials/hosts/schemes, and checking a small route
    allowlist prevents push payloads from becoming an open redirect or a
    notification-driven path traversal primitive.
    """

    if value in (None, ""):
        value = default
    if not isinstance(value, str) or not value or len(value) > MAX_NOTIFICATION_URL_LENGTH:
        raise PushValidationError("Notification URL is invalid.")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise PushValidationError("Notification URL is invalid.")
    if not value.startswith("/") or value.startswith("//"):
        raise PushValidationError("Notification URL must be a safe relative path.")
    parts = urlsplit(value)
    if (
        parts.scheme
        or parts.netloc
        or parts.username
        or parts.password
        or not _allowed_notification_path(parts.path)
    ):
        raise PushValidationError("Notification URL is not an allowed Autumn path.")
    return value


def _bounded_text(
    value: object, *, name: str, length: int, allow_empty: bool = False
) -> str:
    if not isinstance(value, str):
        raise PushValidationError(f"Notification {name} is invalid.")
    value = value.strip()
    if not value and not allow_empty:
        raise PushValidationError(f"Notification {name} is invalid.")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise PushValidationError(f"Notification {name} is invalid.")
    return value[:length]


def _stable_identity(payload: dict) -> str:
    """Choose a deterministic identity for browser deduplication."""

    value = payload.get("identity")
    if value in (None, ""):
        for key in (
            "reminder_id",
            "scheduled_reminder_id",
            "schedule_id",
            "commitment_id",
            "session_id",
            "week_start",
        ):
            if payload.get(key) not in (None, ""):
                value = payload[key]
                break
    if value in (None, ""):
        value = "general"
    if isinstance(value, (dict, list, tuple, set)):
        try:
            value = json.dumps(value, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            value = repr(value)
    value = str(value).strip()
    if not value:
        value = "general"
    # A long arbitrary identity should not consume the payload cap or make a
    # browser tag collide merely because it was truncated at the same prefix.
    if len(value) > MAX_NOTIFICATION_IDENTITY_LENGTH:
        value = hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
    return value


def _stable_tag(payload: dict, *, kind: str, identity: str) -> str:
    value = payload.get("tag")
    if value in (None, ""):
        value = f"autumn-{kind}-{identity}"
    if not isinstance(value, str):
        raise PushValidationError("Notification tag is invalid.")
    value = value.strip()
    if not value or len(value) > MAX_NOTIFICATION_TAG_LENGTH:
        if value:
            value = hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
        else:
            raise PushValidationError("Notification tag is invalid.")
    if not _NOTIFICATION_TOKEN_RE.fullmatch(value):
        raise PushValidationError("Notification tag is invalid.")
    return value


def _normalise_action(action: object, index: int) -> dict[str, str]:
    if not isinstance(action, dict):
        raise PushValidationError("Notification actions must be objects.")
    if "url" not in action or not action.get("url"):
        raise PushValidationError("Notification action URL is required.")
    label_key = "title" if "title" in action else "label"
    label = _bounded_text(
        action.get(label_key), name="action label", length=MAX_NOTIFICATION_ACTION_LABEL_LENGTH
    )
    url = validate_notification_url(action.get("url"))
    identifier = action.get("action", f"action-{index + 1}")
    identifier = _bounded_text(
        identifier, name="action identifier", length=MAX_NOTIFICATION_ACTION_ID_LENGTH
    )
    if not _NOTIFICATION_TOKEN_RE.fullmatch(identifier):
        raise PushValidationError("Notification action identifier is invalid.")
    # Keep the input's label spelling for forward compatibility while always
    # emitting the standard Notification API title field for the service
    # worker.  Unknown action fields are intentionally not forwarded.
    result = {"action": identifier, "title": label, "url": url}
    if label_key == "label":
        result["label"] = label
    return result


def validate_notification_payload(payload: object) -> dict:
    """Validate and bound the browser-facing notification payload.

    This is intentionally usable by future claim services at event creation
    time.  :func:`_serialize_payload` calls it again immediately before
    provider I/O, covering events created by older code or a management job.
    """

    if not isinstance(payload, dict):
        raise PushValidationError("Notification payload must be a JSON object.")
    value = dict(payload)
    kind = value.get("kind", value.get("event_type", "timer"))
    if not isinstance(kind, str) or not kind.strip():
        raise PushValidationError("Notification kind is invalid.")
    kind = kind.strip()[:MAX_NOTIFICATION_ACTION_ID_LENGTH]
    if not _NOTIFICATION_TOKEN_RE.fullmatch(kind):
        raise PushValidationError("Notification kind is invalid.")
    identity = _stable_identity(value)
    tag = _stable_tag(value, kind=kind, identity=identity)

    output = {}
    for key, length in (
        ("title", MAX_NOTIFICATION_TITLE_LENGTH),
        ("body", MAX_NOTIFICATION_BODY_LENGTH),
    ):
        if key in value:
            output[key] = _bounded_text(
                value[key], name=key, length=length, allow_empty=key == "body"
            )
    output["url"] = validate_notification_url(value.get("url"))
    output["kind"] = kind
    output["identity"] = identity
    output["tag"] = tag
    if "event_type" in value:
        event_type = value["event_type"]
        if not isinstance(event_type, str):
            raise PushValidationError("Notification event type is invalid.")
        output["event_type"] = event_type.strip()[:MAX_NOTIFICATION_ACTION_ID_LENGTH]

    for key in (
        "session_id",
        "session_uuid",
        "reminder_id",
        "scheduled_reminder_id",
        "schedule_id",
        "commitment_id",
        "week_start",
        "scheduled_at",
    ):
        if key in value:
            output[key] = value[key]
    if "actions" in value:
        actions = value["actions"]
        if not isinstance(actions, list) or len(actions) > MAX_NOTIFICATION_ACTIONS:
            raise PushValidationError(
                f"Notification actions must contain at most {MAX_NOTIFICATION_ACTIONS} items."
            )
        normalised_actions = [
            _normalise_action(action, index) for index, action in enumerate(actions)
        ]
        if len({action["action"] for action in normalised_actions}) != len(
            normalised_actions
        ):
            raise PushValidationError("Notification action identifiers must be unique.")
        output["actions"] = normalised_actions
    return output


def _event_terminal_status(event, status: str, *, error: str | None = None):
    now = timezone.now()
    fields = {"status": status, "delivered_at": now if status == "delivered" else None}
    if error is not None:
        fields.update(last_error=error[:MAX_ERROR_LENGTH], last_error_at=now)
    else:
        fields.update(last_error="", last_error_at=None)
    NotificationEvent.objects.filter(pk=event.pk, status="pending").update(**fields)


def _serialize_payload(payload: object) -> str:
    # Keep only fields understood by the service worker and validate them at
    # the provider boundary as well as at event creation.  Web Push encryption
    # adds framing bytes, so MAX_PAYLOAD_BYTES remains a conservative ceiling
    # rather than allowing an event payload to become a provider failure.
    payload = validate_notification_payload(payload)
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
            # Retain a valid, bounded notification even for a caller-supplied
            # payload containing huge user text or future fields. Preserve the
            # stable identity/tag so a fallback cannot collapse into an
            # unrelated browser notification.
            value = json.dumps(
                {
                    "title": "Autumn",
                    "body": "Your notification is ready.",
                    "url": "/timers/",
                    "kind": payload.get("kind", "timer"),
                    "identity": payload.get("identity", "general"),
                    "tag": payload.get("tag", "autumn-timer-general"),
                },
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


def _delivery_summary(event):
    deliveries = list(
        NotificationDelivery.objects.filter(event=event).values_list(
            "status", "last_error", "attempts", "delivered_at"
        )
    )
    counts = Counter(status for status, _, _, _ in deliveries)
    accepted_at = max(
        (delivered_at for _, _, _, delivered_at in deliveries if delivered_at is not None),
        default=None,
    )
    return {
        "devices_targeted": len(deliveries),
        "devices_delivered": counts["delivered"],
        "devices_pending": counts["pending"] + counts["processing"],
        "devices_failed": counts["failed"],
        "devices_expired": counts["expired"],
        "devices_unavailable": counts["unavailable"],
        "attempts": sum(attempts or 0 for _, _, attempts, _ in deliveries),
        "provider_accepted_at": accepted_at,
        "errors": [
            error
            for status, error, _, _ in deliveries
            if status == "failed" and error
        ],
    }


def _event_state_from_summary(summary):
    statuses = {
        status
        for status, count in (
            ("pending", summary["devices_pending"]),
            ("delivered", summary["devices_delivered"]),
            ("failed", summary["devices_failed"]),
            ("expired", summary["devices_expired"]),
            ("unavailable", summary["devices_unavailable"]),
        )
        if count
    }
    if not statuses:
        return "unavailable", "No active subscriptions"
    if "pending" in statuses:
        return "pending", None
    if "delivered" in statuses:
        return "delivered", None
    if statuses <= {"unavailable", "expired"}:
        return "unavailable", "No active subscriptions could receive this notification"
    errors = summary["errors"]
    return "failed", (errors[0] if errors else "All push deliveries failed")


def _log_dispatch_result(event, status, summary, *, error=None):
    """Write an operator-safe, searchable delivery summary to the app log."""

    accepted_at = summary["provider_accepted_at"]
    logger.info(
        "notification_dispatch event_id=%s event_type=%s user_id=%s "
        "username=%s scheduled_at=%s status=%s devices_targeted=%s "
        "devices_delivered=%s devices_pending=%s devices_failed=%s "
        "devices_expired=%s devices_unavailable=%s attempts=%s "
        "provider_accepted_at=%s error=%s",
        event.pk,
        event.event_type,
        event.user_id,
        json.dumps(event.user.get_username(), ensure_ascii=True),
        event.scheduled_at.isoformat(),
        status,
        summary["devices_targeted"],
        summary["devices_delivered"],
        summary["devices_pending"],
        summary["devices_failed"],
        summary["devices_expired"],
        summary["devices_unavailable"],
        summary["attempts"],
        accepted_at.isoformat() if accepted_at is not None else "-",
        json.dumps(error or "", ensure_ascii=True),
    )


def _log_device_failure(event, delivery, status, *, provider_status=None, error=None):
    logger.warning(
        "notification_device_failure event_id=%s event_type=%s user_id=%s "
        "subscription_id=%s status=%s provider_status=%s attempt=%s error=%s",
        event.pk,
        event.event_type,
        event.user_id,
        delivery.subscription_id,
        status,
        provider_status if provider_status is not None else "-",
        delivery.attempts or 0,
        json.dumps(_safe_error(error) if error is not None else "", ensure_ascii=True),
    )


def _active_subscription_count(user_id):
    return PushSubscription.objects.filter(user_id=user_id, active=True).count()


def _empty_delivery_summary(*, targeted=0, unavailable=0):
    return {
        "devices_targeted": targeted,
        "devices_delivered": 0,
        "devices_pending": 0,
        "devices_failed": 0,
        "devices_expired": 0,
        "devices_unavailable": unavailable,
        "attempts": 0,
        "provider_accepted_at": None,
        "errors": [],
    }


def _event_payload(event) -> dict:
    """Attach a durable fallback identity without changing timer payloads."""

    payload = dict(event.payload) if isinstance(event.payload, dict) else {}
    # Legacy timer events derive their identity from reminder/session IDs and
    # intentionally default to the old ``autumn-timer-*`` category/tag.  For
    # an event with no source identity at all, use its durable unique key so
    # unrelated events cannot collapse into one browser notification.
    identity_keys = (
        "identity",
        "reminder_id",
        "scheduled_reminder_id",
        "schedule_id",
        "commitment_id",
        "session_id",
        "week_start",
    )
    if not any(payload.get(key) not in (None, "") for key in identity_keys):
        payload["identity"] = event.dedupe_key
    return payload


def dispatch_event(event_id: int, *, now=None) -> str:
    """Fan out and deliver one pending event without holding locks on I/O."""

    now = now or timezone.now()
    try:
        event = NotificationEvent.objects.select_related("user").get(pk=event_id)
    except NotificationEvent.DoesNotExist:
        return "missing"
    if event.status != "pending":
        return event.status
    if not push_configured():
        active_devices = _active_subscription_count(event.user_id)
        summary = _empty_delivery_summary(
            targeted=active_devices,
            unavailable=active_devices,
        )
        error = "VAPID is not configured"
        _event_terminal_status(event, "unavailable", error=error)
        _log_dispatch_result(event, "unavailable", summary, error=error)
        return "unavailable"

    with transaction.atomic():
        event = (
            NotificationEvent.objects.select_for_update()
            .select_related("user")
            .get(pk=event.pk)
        )
        if event.status != "pending":
            return event.status
        has_deliveries = _fanout_event(event)
        if not has_deliveries:
            error = "No active subscriptions"
            summary = _empty_delivery_summary()
            _event_terminal_status(event, "unavailable", error=error)
            _log_dispatch_result(event, "unavailable", summary, error=error)
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
            send_push(delivery.subscription, _event_payload(event))
        except PushUnavailable as exc:
            NotificationDelivery.objects.filter(pk=delivery.pk).update(
                status="unavailable",
                last_error=_safe_error(exc),
                last_error_at=timezone.now(),
                lease_until=None,
                next_attempt_at=None,
            )
            _log_device_failure(event, delivery, "unavailable", error=exc)
        except PushValidationError as exc:
            # A malformed event is a permanent producer error. Retrying it
            # cannot make an unsafe URL or oversized action become valid and
            # would keep the outbox pending until the retry cap is exhausted.
            NotificationDelivery.objects.filter(pk=delivery.pk).update(
                status="failed",
                last_error=_safe_error(exc),
                last_error_at=timezone.now(),
                lease_until=None,
                next_attempt_at=None,
            )
            _log_device_failure(event, delivery, "failed", error=exc)
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
            _log_device_failure(
                event,
                delivery,
                status,
                provider_status=code,
                error=exc,
            )
        else:
            NotificationDelivery.objects.filter(pk=delivery.pk).update(
                status="delivered",
                delivered_at=timezone.now(),
                lease_until=None,
                next_attempt_at=None,
                last_error="",
                last_error_at=None,
            )

    summary = _delivery_summary(event)
    status, error = _event_state_from_summary(summary)
    if status != "pending":
        _event_terminal_status(event, status, error=error)
    _log_dispatch_result(event, status, summary, error=error)
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
