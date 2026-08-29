"""Shared timer-reminder dispatch pass and an opt-in in-process dispatcher.

Delivery has two supported shapes:

* the bounded ``dispatch_timer_reminders`` management command (cron), and
* an env-gated daemon thread started from ``CoreConfig.ready()`` so a single
  web process (``runserver`` locally, gunicorn on a PaaS) delivers on its own.

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


def run_dispatch_pass(*, limit=100, now=None):
    """Run one bounded dispatch pass.

    Returns ``(stopped_count, claimed, flushed)`` where ``claimed`` is whatever
    ``claim_due_reminders`` returned (a list of events, or a count).
    """
    from django.utils import timezone

    from core.services.push import flush_outbox
    from core.services.reminders import claim_due_reminders
    from core.utils import stop_expired_timers

    now = now or timezone.now()
    stopped = stop_expired_timers(now=now)
    claimed = claim_due_reminders(now=now, limit=limit)
    flushed = flush_outbox(limit=limit, now=now)
    return len(stopped), claimed, flushed


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

    interval = _interval_seconds()
    limit = int(getattr(settings, "PUSH_DISPATCH_LIMIT", 100))
    lock_token = uuid4().hex
    try:
        acquired = cache.add(LOCK_KEY, lock_token, timeout=max(60, int(interval) + 30))
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


def _interval_seconds():
    from django.conf import settings

    try:
        return max(1.0, float(getattr(settings, "PUSH_DISPATCH_INTERVAL_SECONDS", 15.0)))
    except (TypeError, ValueError):
        return 15.0


def _dispatch_loop():
    # Wait one interval first: touching the database from a thread started in
    # AppConfig.ready() while apps are still loading is discouraged by Django.
    time.sleep(_interval_seconds())
    last_error = None
    while True:
        try:
            _dispatch_once()
            last_error = None
        except Exception as exc:  # Never let the dispatcher thread die.
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
        time.sleep(_interval_seconds())


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
