"""Claim timer reminders and deliver their durable push outbox events."""

from __future__ import annotations

import time
from uuid import uuid4

from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.utils import timezone

from core.services.push import flush_outbox
from core.utils import stop_expired_timers


class Command(BaseCommand):
    help = "Dispatch due timer reminder and auto-stop Web Push notifications."
    lock_key = "autumn:dispatch_timer_reminders:lock"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "--once",
            action="store_true",
            help="Run one bounded pass (the default, suitable for cron).",
        )
        group.add_argument(
            "--loop",
            action="store_true",
            help="Poll until --max-seconds is reached.",
        )
        parser.add_argument("--max-seconds", type=float, default=30.0)
        parser.add_argument("--interval-seconds", type=float, default=1.0)
        parser.add_argument("--limit", type=int, default=100)

    def _claim_due(self, *, now, limit):
        try:
            from core.services.reminders import claim_due_reminders
        except ImportError as exc:  # Backend reminder slice not installed yet.
            raise CommandError("Reminder claiming service is unavailable.") from exc
        return claim_due_reminders(now=now, limit=limit)

    def _pass(self, *, limit):
        now = timezone.now()
        stopped = stop_expired_timers(now=now)
        claimed = self._claim_due(now=now, limit=limit)
        flushed = flush_outbox(limit=limit, now=now)
        return len(stopped), claimed, flushed

    def _lock_timeout(self, options):
        # Keep the lock through the complete bounded loop and a small cleanup
        # margin.  Shared cache backends make this invariant hold across web
        # and worker processes; a cache outage is handled as a safe no-op.
        return max(
            60,
            int(options["max_seconds"] + options["interval_seconds"] + 30),
        )

    def handle(self, *args, **options):
        if options["max_seconds"] <= 0:
            raise CommandError("--max-seconds must be positive.")
        if options["interval_seconds"] < 0:
            raise CommandError("--interval-seconds cannot be negative.")
        if options["limit"] < 1:
            raise CommandError("--limit must be positive.")

        lock_token = uuid4().hex
        try:
            acquired = cache.add(
                self.lock_key,
                lock_token,
                timeout=self._lock_timeout(options),
            )
        except Exception as exc:  # A broken cache must not run two dispatchers.
            raise CommandError("Unable to acquire the timer dispatcher lock.") from exc
        if not acquired:
            self.stdout.write("Timer reminder dispatcher is already running.")
            return

        deadline = time.monotonic() + options["max_seconds"]
        total_stopped = total_claimed = total_flushed = 0
        try:
            while True:
                close_old_connections()
                stopped, claimed, flushed = self._pass(limit=options["limit"])
                total_stopped += stopped
                total_claimed += claimed if isinstance(claimed, int) else len(claimed)
                total_flushed += flushed
                if not options["loop"] or time.monotonic() >= deadline:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(options["interval_seconds"], remaining))
            self.stdout.write(
                self.style.SUCCESS(
                    "Processed timers: stopped=%d claimed=%d flushed=%d"
                    % (total_stopped, total_claimed, total_flushed)
                )
            )
        finally:
            # Avoid deleting a lock that may have expired and been acquired by
            # a later process.  The get/delete pair is best effort; the TTL is
            # the hard safety boundary.
            try:
                if cache.get(self.lock_key) == lock_token:
                    cache.delete(self.lock_key)
            except Exception:
                pass
