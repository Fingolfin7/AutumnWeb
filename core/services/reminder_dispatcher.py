"""Shared timer-reminder dispatch pass and an opt-in in-process dispatcher.

Delivery has two supported shapes:

* the bounded ``dispatch_timer_reminders`` management command (cron), and
* an env-gated daemon thread started from ``CoreConfig.ready()`` so a web
  process (``runserver`` locally, gunicorn on a PaaS) delivers on its own.

Both run the same :func:`run_dispatch_pass` under the same best-effort cache
lock key, so an external cron and the in-process thread do not overlap a pass
when they share a cache backend.  The durable concurrency guarantees live in
the database layer (conditional-update claiming), not in that lock.

Keep this module import-light: it is imported from ``AppConfig.ready()``.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from uuid import uuid4

logger = logging.getLogger(__name__)

# Reuse the management command's lock key so cron and the in-process thread
# serialise against each other on a shared cache backend.
LOCK_KEY = "autumn:dispatch_timer_reminders:lock"

_thread = None
_thread_lock = threading.Lock()
_wake_event = threading.Event()

# An idle production database must have at least one uninterrupted five-minute
# window in which Neon can suspend compute.  Local commits normally wake the
# dispatcher immediately; this is only the durable fallback for writes which
# bypass this process's signals.
MIN_SAFETY_RESCAN_SECONDS = 300.0
DEFAULT_SAFETY_RESCAN_SECONDS = 900.0
LOCK_RETRY_SECONDS = 5.0
STARTUP_DELAY_SECONDS = 1.0


def run_dispatch_pass(*, limit=100, now=None):
    """Run one bounded dispatch pass.

    Returns ``(stopped_count, claimed, flushed)`` where ``claimed`` is whatever
    ``claim_due_reminders`` returned (a list of events, or a count).  When the
    optional proactive claim service is installed, its three categories are
    appended to that same collection; the public three-tuple is unchanged.
    """
    from django.utils import timezone

    from core.services.push import flush_outbox
    from core.services.reminders import claim_due_reminders
    from core.utils import stop_expired_timers

    now = now or timezone.now()
    stopped = stop_expired_timers(now=now)
    claimed = claim_due_reminders(now=now, limit=limit)
    claimed = _claim_proactive_notifications(claimed, now=now, limit=limit)
    flushed = flush_outbox(limit=limit, now=now)
    claimed_count = claimed if isinstance(claimed, int) else len(claimed)
    if stopped or claimed_count or flushed:
        logger.info(
            "notification_dispatch_pass stopped=%s claimed=%s outbox_flushed=%s",
            len(stopped),
            claimed_count,
            flushed,
        )
    return len(stopped), claimed, flushed


def _claim_proactive_notifications(timer_claimed, *, now, limit):
    """Append optional scheduled/commitment/review claims defensively.

    The proactive claim module is intentionally not imported at module load:
    timer delivery remains deployable while that later slice is absent or its
    migration has not yet run.  A future module may expose one combined
    ``claim_due_notifications`` function or the three category functions
    listed below.  Each function receives the same pass instant and a
    remaining bounded limit, and must return a list of newly claimed events.
    """

    try:
        from core.services import proactive_notifications
    except ImportError:
        return timer_claimed

    if isinstance(timer_claimed, int):
        combined = []
        timer_count = timer_claimed
    else:
        try:
            combined = list(timer_claimed or [])
        except TypeError:
            # Preserve the old contract for an unusual count-like return.
            return timer_claimed
        timer_count = len(combined)

    remaining = max(0, int(limit) - timer_count)
    if not remaining:
        return combined

    combined_claimer = next(
        (
            getattr(proactive_notifications, name, None)
            for name in (
                "claim_due_notifications",
                "claim_due_proactive_notifications",
            )
            if callable(getattr(proactive_notifications, name, None))
        ),
        None,
    )
    if callable(combined_claimer):
        try:
            extra = combined_claimer(now=now, limit=remaining)
        except ImportError:
            # A partially deployed proactive module may still be waiting for
            # its model migration.  Timer claims must continue to run.
            return combined
        if extra:
            combined.extend(extra if isinstance(extra, (list, tuple)) else [extra])
        return combined

    for names in (
        ("claim_due_scheduled_reminders", "claim_due_scheduled"),
        ("claim_due_commitment_checks", "claim_due_commitments"),
        ("claim_due_weekly_reviews", "claim_due_weekly_review"),
    ):
        name = next(
            (candidate for candidate in names if callable(getattr(proactive_notifications, candidate, None))),
            None,
        )
        claimer = getattr(proactive_notifications, name, None) if name else None
        if not callable(claimer):
            continue
        remaining = max(0, int(limit) - len(combined))
        if not remaining:
            break
        try:
            extra = claimer(now=now, limit=remaining)
        except ImportError:
            # Keep the timer-only pass usable during a rolling deployment.
            continue
        if extra:
            combined.extend(extra if isinstance(extra, (list, tuple)) else [extra])
    return combined


def should_start_dispatcher(argv, environ, *, enabled):
    """Decide whether this process should own the dispatcher thread.

    Pure function: no imports of Django state, no side effects.  Only a web
    server process should run it -- never ``test``, ``migrate``, ``check``, or
    the dispatch command itself.
    """
    if not enabled:
        return False

    argv = list(argv or [])
    if not argv:
        return False

    program = os.path.basename(str(argv[0])).lower()
    command = str(argv[1]) if len(argv) > 1 else ""

    if program.startswith("manage.py") or program == "django-admin":
        if command != "runserver":
            # Any other management command (test, migrate, check, the cron
            # dispatcher itself) must stay single-purpose.
            return False
        if "--noreload" in argv:
            # Autoreload is off, so this process is the only one.
            return True
        # Under autoreload only the child process (RUN_MAIN=true) should run it.
        return (environ or {}).get("RUN_MAIN") == "true"

    if any(server in program for server in ("gunicorn", "uvicorn", "daphne")):
        return True

    return False


def _dispatch_once():
    """One locked pass. Returns True when the pass actually ran."""
    from django.conf import settings
    from django.core.cache import cache
    from django.db import close_old_connections

    close_old_connections()

    limit = int(getattr(settings, "PUSH_DISPATCH_LIMIT", 100))
    lock_token = uuid4().hex
    try:
        acquired = cache.add(LOCK_KEY, lock_token, timeout=300)
    except Exception:
        # A broken cache must not run two dispatchers; skip this tick.
        logger.debug("Timer dispatcher lock unavailable; skipping pass.", exc_info=True)
        return False
    if not acquired:
        return False

    try:
        run_dispatch_pass(limit=limit)
    finally:
        # Never delete a lock that expired and was re-acquired elsewhere; the
        # TTL is the hard safety boundary.
        try:
            if cache.get(LOCK_KEY) == lock_token:
                cache.delete(LOCK_KEY)
        except Exception:
            pass
    return True


def _safety_rescan_seconds():
    from django.conf import settings

    try:
        configured = float(
            getattr(
                settings,
                "PUSH_DISPATCH_SAFETY_RESCAN_SECONDS",
                DEFAULT_SAFETY_RESCAN_SECONDS,
            )
        )
    except (TypeError, ValueError):
        configured = DEFAULT_SAFETY_RESCAN_SECONDS
    return max(MIN_SAFETY_RESCAN_SECONDS, configured)


def wake_dispatcher():
    """Wake this process's dispatcher after relevant state commits."""

    _wake_event.set()


def wake_dispatcher_on_commit():
    """Schedule a wake without letting the thread observe uncommitted state."""

    from django.db import transaction

    transaction.on_commit(wake_dispatcher)


def next_dispatch_at(*, now=None):
    """Return the earliest persisted instant that can make a pass useful.

    All sources are combined into one ``UNION ALL`` query.  A pending event
    with no live deliveries is due immediately; delivery retries wait for
    ``next_attempt_at`` and abandoned processing leases wait for
    ``lease_until``.  This mirrors ``flush_outbox`` without changing its
    claiming, retry, or terminal-state behavior.
    """

    from django.db.models import (
        DateTimeField,
        Exists,
        F,
        Min,
        OuterRef,
        Q,
        Value,
    )
    from django.db.models.functions import Coalesce
    from django.utils import timezone

    from core.models import (
        NotificationDelivery,
        NotificationEvent,
        NotificationPreference,
        ScheduledReminder,
        Sessions,
        TimerReminder,
    )

    now = now or timezone.now()
    instant = Value(now, output_field=DateTimeField())

    def minimum(queryset, expression):
        # Group by one constant so an empty source contributes no UNION row,
        # while a populated source contributes only its indexed minimum.
        return (
            queryset.order_by()
            .annotate(_dispatch_group=Value(1))
            .values("_dispatch_group")
            .annotate(dispatch_at=Min(expression))
            .exclude(dispatch_at__isnull=True)
            .values_list("dispatch_at")
        )

    deadlines = [
        minimum(
            Sessions.objects.filter(
                end_time__isnull=True, auto_stop_at__isnull=False
            ),
            F("auto_stop_at"),
        ),
        minimum(
            TimerReminder.objects.filter(
                active=True,
                next_fire_at__isnull=False,
                session__end_time__isnull=True,
            ),
            F("next_fire_at"),
        ),
        minimum(
            ScheduledReminder.objects.filter(
                Q(user__notification_preferences__isnull=True)
                | Q(
                    user__notification_preferences__scheduled_reminders_enabled=True
                ),
                active=True,
                next_fire_at__isnull=False,
            ),
            F("next_fire_at"),
        ),
        minimum(
            NotificationPreference.objects.filter(
                commitment_checks_enabled=True,
                next_commitment_check_at__isnull=False,
            ),
            F("next_commitment_check_at"),
        ),
        minimum(
            NotificationPreference.objects.filter(
                weekly_review_enabled=True,
                next_weekly_review_at__isnull=False,
            ),
            F("next_weekly_review_at"),
        ),
    ]

    live_deliveries = NotificationDelivery.objects.filter(
        event_id=OuterRef("pk"), status__in=("pending", "processing")
    )
    immediate_events = minimum(
        NotificationEvent.objects.filter(status="pending")
        .annotate(has_live_delivery=Exists(live_deliveries))
        .filter(has_live_delivery=False),
        instant,
    )
    pending_deliveries = minimum(
        NotificationDelivery.objects.filter(
            event__status="pending", status="pending"
        ),
        Coalesce("next_attempt_at", instant),
    )
    processing_deliveries = minimum(
        NotificationDelivery.objects.filter(
            event__status="pending", status="processing"
        ),
        Coalesce("lease_until", instant),
    )
    deadlines.extend((immediate_events, pending_deliveries, processing_deliveries))

    combined = deadlines[0].union(*deadlines[1:], all=True).order_by("dispatch_at")
    row = combined.first()
    return row[0] if row is not None else None


def _dispatch_step(*, now=None):
    """Inspect persisted deadlines and run a pass only when work is due.

    Returns the number of seconds to wait.  ``None`` means a pass ran and the
    caller should immediately rescan, which also drains bounded backlogs.
    """

    from django.utils import timezone

    now = now or timezone.now()
    deadline = next_dispatch_at(now=now)
    if deadline is not None and deadline <= now:
        return None if _dispatch_once() else LOCK_RETRY_SECONDS

    until_deadline = (
        (deadline - now).total_seconds() if deadline is not None else float("inf")
    )
    return min(_safety_rescan_seconds(), max(0.0, until_deadline))


def _error_retry_seconds(consecutive_errors):
    """Back off repeated failures while still recovering without intervention."""

    return min(300.0, 15.0 * (2 ** max(0, consecutive_errors - 1)))


def _dispatch_loop():
    # Let AppConfig.ready() and the rest of Django startup finish before this
    # thread performs its initial durable deadline scan.
    time.sleep(STARTUP_DELAY_SECONDS)
    last_error = None
    consecutive_errors = 0
    while True:
        # Clear before scanning. A commit racing with the scan sets the event
        # again, so the following wait returns immediately and cannot miss it.
        _wake_event.clear()
        try:
            wait_seconds = _dispatch_step()
            last_error = None
            consecutive_errors = 0
        except Exception as exc:  # Never let the dispatcher thread die.
            consecutive_errors += 1
            signature = f"{type(exc).__name__}: {exc}"
            if signature == last_error:
                # Unmigrated database or a persistent outage: do not spam the
                # same traceback every interval.
                logger.debug("Timer dispatcher pass failed again: %s", signature)
            else:
                logger.warning(
                    "Timer dispatcher pass failed: %s", signature, exc_info=True
                )
                last_error = signature
            wait_seconds = _error_retry_seconds(consecutive_errors)
        finally:
            # This daemon has its own thread-local connection. Releasing it
            # before a potentially long wait avoids holding Neon open and also
            # makes a resumed compute reconnect cleanly.
            try:
                from django.db import connections

                connections.close_all()
            except Exception:
                logger.debug(
                    "Could not close dispatcher database connections.", exc_info=True
                )

        if wait_seconds is not None:
            _wake_event.wait(wait_seconds)


def start_dispatcher_thread():
    """Start the single daemon dispatcher thread. Repeat calls are no-ops."""
    global _thread
    with _thread_lock:
        if _thread is not None:
            return _thread
        thread = threading.Thread(
            target=_dispatch_loop,
            name="autumn-timer-dispatcher",
            daemon=True,
        )
        _thread = thread
        thread.start()
        logger.info("Started in-process timer reminder dispatcher thread.")
        return thread
