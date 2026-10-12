"""Keep search vectors current in the background, shortly after edits.

Edits to sessions, projects and subprojects (see ``core.signals``) and turning
on AI features with an OpenAI key request a sync for that account once their
transaction commits; related searches request one too, at most every
``SEARCH_RECHECK_SECONDS``, which catches writes made outside a web process
(a CLI import on the server). A daemon thread in each web process runs the
syncs ``EDIT_DELAY_SECONDS`` later, one at a time, so a burst of edits (an
import, a rename touching hundreds of sessions) becomes one run.

A sync re-embeds whatever is missing or stale for the account, not just the
record that asked, so a run lost to a restart or deploy is caught by the next
request, and edits that bypass model signals (queryset ``update()``) are
picked up too. ``manage.py embed_sessions`` remains for backfills and repair.

Only web server processes run the thread; tests and other management
commands never start it, so their writes request nothing.
"""
import logging
import os
import sys
import threading
import time

from django.conf import settings
from django.db import connections, transaction

logger = logging.getLogger(__name__)

EDIT_DELAY_SECONDS = 10.0
SEARCH_RECHECK_SECONDS = 10 * 60
FAILURE_BACKOFF_SECONDS = 5 * 60
FAILURE_RETRIES = 3


def is_web_process(argv, environ):
    """Whether this process serves requests (and so may own the sync thread).

    Pure function. The thread starts lazily on the first request for a sync,
    so under Gunicorn it starts inside a worker, after the fork.
    """
    argv = list(argv or [])
    if not argv:
        return False
    program = os.path.basename(str(argv[0])).lower()
    if program.startswith("manage.py") or program == "django-admin":
        if len(argv) < 2 or argv[1] != "runserver":
            return False
        # Under autoreload only the child (RUN_MAIN=true) serves requests.
        return "--noreload" in argv or (environ or {}).get("RUN_MAIN") == "true"
    return any(server in program for server in ("gunicorn", "uvicorn", "daphne"))


class SyncQueue:
    """Per-account sync requests, coalesced and run one at a time.

    ``run(user_id)`` performs one sync and returns whether it succeeded. A
    failed account waits ``FAILURE_BACKOFF_SECONDS`` before its next run, so a
    broken key isn't retried on every edit, and is retried on its own up to
    ``FAILURE_RETRIES`` times so a passing outage doesn't leave it stale.
    """

    def __init__(self, run, *, clock=time.monotonic):
        self._run = run
        self._clock = clock
        self._lock = threading.Condition()
        self._due = {}  # user id -> when its sync should run
        self._checked = {}  # user id -> when its last successful sync finished
        self._blocked = {}  # user id -> end of its failure backoff
        self._failures = {}  # user id -> consecutive failed syncs

    def request(self, user_id, *, delay=EDIT_DELAY_SECONDS, recheck=False):
        """Ask for a sync of ``user_id``; a pending request absorbs this one.

        ``recheck`` marks a speculative request (from a search): it is dropped
        if the account finished a sync within ``SEARCH_RECHECK_SECONDS``.
        """
        with self._lock:
            now = self._clock()
            if user_id in self._due:
                return
            if recheck:
                last = self._checked.get(user_id)
                if last is not None and now - last < SEARCH_RECHECK_SECONDS:
                    return
            self._due[user_id] = max(now + delay, self._blocked.get(user_id, now))
            self._lock.notify()

    def pending(self):
        with self._lock:
            return dict(self._due)

    def run_due(self):
        """Run every sync that is due now, earliest first."""
        while True:
            with self._lock:
                now = self._clock()
                ready = [user_id for user_id, due in self._due.items() if due <= now]
                if not ready:
                    return
                user_id = min(ready, key=self._due.get)
                del self._due[user_id]
            # Outside the lock: a sync takes seconds, and edits made meanwhile
            # must be able to queue another run for this account.
            succeeded = self._run(user_id)
            with self._lock:
                now = self._clock()
                if succeeded:
                    self._checked[user_id] = now
                    self._blocked.pop(user_id, None)
                    self._failures.pop(user_id, None)
                    continue
                failures = self._failures.get(user_id, 0) + 1
                self._failures[user_id] = failures
                blocked = now + FAILURE_BACKOFF_SECONDS
                self._blocked[user_id] = blocked
                if user_id in self._due:
                    # An edit made during the failed run waits out the backoff too.
                    self._due[user_id] = max(self._due[user_id], blocked)
                elif failures <= FAILURE_RETRIES:
                    self._due[user_id] = blocked

    def _wait(self):
        with self._lock:
            if self._due:
                timeout = min(self._due.values()) - self._clock()
                if timeout <= 0:
                    return
            else:
                timeout = None
            self._lock.wait(timeout)

    def serve_forever(self):
        while True:
            try:
                self.run_due()
            except Exception:
                logger.exception("semantic_sync_queue_error")
                time.sleep(EDIT_DELAY_SECONDS)
            self._wait()


def sync_account(user_id):
    """Embed the account's missing or stale records; False on failure."""
    from django.contrib.auth.models import User

    from core.services.semantic_search import (
        SYNC_TIMEOUT_SECONDS,
        embedder_for,
        semantic_search_available,
        sync_embeddings,
    )

    try:
        user = User.objects.select_related("profile").filter(pk=user_id).first()
        if user is None or not semantic_search_available(user):
            return True
        embedder = embedder_for(user, timeout=SYNC_TIMEOUT_SECONDS, max_retries=2)
        if embedder is None:
            return True
        report = sync_embeddings(user, embedder)
        logger.info(
            "semantic_sync user_id=%s sessions_embedded=%s projects_embedded=%s",
            user_id,
            report.sessions.embedded,
            report.projects.embedded,
        )
        return True
    except Exception as exc:
        # The category only: provider errors can echo request content.
        logger.warning(
            "semantic_sync_failed user_id=%s error_category=%s", user_id, type(exc).__name__
        )
        return False


def _sync_on_thread(user_id):
    # No request cycle closes this thread's database connection, so do it
    # here; the next run opens a fresh one.
    try:
        return sync_account(user_id)
    finally:
        connections.close_all()


_queue = None
_queue_lock = threading.Lock()


def _get_queue():
    global _queue
    with _queue_lock:
        if _queue is None:
            queue = SyncQueue(_sync_on_thread)
            threading.Thread(target=queue.serve_forever, name="semantic-sync", daemon=True).start()
            _queue = queue
        return _queue


def background_sync_enabled():
    return settings.SEMANTIC_SYNC_ON_WRITE and is_web_process(sys.argv, os.environ)


def request_sync(user_id, *, recheck=False):
    """Queue a background sync for ``user_id``; never raises."""
    if not user_id or not background_sync_enabled():
        return
    try:
        _get_queue().request(user_id, recheck=recheck)
    except Exception:
        logger.exception("semantic_sync_request_failed")


def request_sync_on_commit(user_id):
    """Queue a sync once the current transaction commits, so it sees the edit."""
    if user_id and background_sync_enabled():
        transaction.on_commit(lambda: request_sync(user_id))
