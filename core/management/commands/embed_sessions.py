"""Embed completed sessions and projects whose search vector is missing or stale."""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from core.services.semantic_search import (
    MODEL,
    SYNC_TIMEOUT_SECONDS,
    embedder_for,
    sync_embeddings,
)


class Command(BaseCommand):
    help = (
        "Embed new and changed sessions and projects for meaning-based search. "
        "Only accounts with AI features on and an OpenAI API key are processed, "
        "each with its own key. Web processes already do this in the background "
        "after edits; use this for backfills and repair. Safe to re-run."
    )

    def add_arguments(self, parser):
        parser.add_argument("--username", type=str, help="Only this user.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be embedded without calling the provider.",
        )
        parser.add_argument("--batch-size", type=int, default=100)
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="At most this many sessions, and this many projects, per user per run (newest first).",
        )

    def handle(self, *args, **options):
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be positive.")
        if options["limit"] is not None and options["limit"] < 1:
            raise CommandError("--limit must be positive.")

        users = User.objects.filter(
            profile__ai_features_enabled=True, profile__openai_api_key_enc__isnull=False
        ).select_related("profile").order_by("pk")
        if options["username"]:
            users = users.filter(username=options["username"])
            if not users.exists():
                if not User.objects.filter(username=options["username"]).exists():
                    raise CommandError(f"User '{options['username']}' not found.")
                self.stdout.write(f"{options['username']}: AI features off or no OpenAI key; skipped.")
                return

        failures = 0
        for user in users:
            try:
                embedder = embedder_for(user, timeout=SYNC_TIMEOUT_SECONDS, max_retries=2)
                if embedder is None:
                    self.stdout.write(f"{user.username}: OpenAI key unreadable; skipped.")
                    continue
                result = sync_embeddings(
                    user,
                    embedder,
                    batch_size=options["batch_size"],
                    limit=options["limit"],
                    dry_run=options["dry_run"],
                )
            except Exception as exc:
                failures += 1
                # The category only: provider errors can echo request content.
                self.stderr.write(f"{user.username}: embedding failed ({type(exc).__name__}).")
                continue
            parts = []
            for label, kind in (("sessions", result.sessions), ("projects", result.projects)):
                done = (
                    f"{kind.pending} to embed" if options["dry_run"] else f"{kind.embedded} embedded"
                )
                parts.append(f"{kind.total} {label} ({kind.fresh} current, {done})")
            line = f"{user.username}: " + "; ".join(parts)
            if options["dry_run"]:
                chars = result.sessions.pending_chars + result.projects.pending_chars
                line += f"; ~{chars // 4} tokens, {MODEL}"
            self.stdout.write(line + ".")
        if failures:
            raise CommandError(f"Embedding failed for {failures} user(s).")
