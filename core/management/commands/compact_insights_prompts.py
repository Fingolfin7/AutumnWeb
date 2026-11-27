from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from llm_insights.models import LLMMessage
from llm_insights.session_context import compact_session_prompt, has_session_slot


class Command(BaseCommand):
    help = "Measure or remove copied session data from historical Insights system prompts."

    def add_arguments(self, parser):
        parser.add_argument("--username", help="Limit the scan to this account.")
        parser.add_argument("--apply", action="store_true", help="Write the compacted prompts.")

    def handle(self, *args, username, apply, **options):
        messages = LLMMessage.objects.filter(role="system")
        if username:
            user = get_user_model().objects.filter(username=username).first()
            if user is None:
                raise CommandError("No account found for that username.")
            messages = messages.filter(chat__user=user)

        scanned = updated = saved = skipped = unrecognised = 0
        for pk, original in messages.order_by("pk").values_list("pk", "content").iterator(chunk_size=50):
            scanned += 1
            compacted = compact_session_prompt(original)
            if not has_session_slot(compacted):
                unrecognised += 1
                continue
            if len(compacted) >= len(original):
                continue
            if apply and not messages.filter(pk=pk, content=original).update(content=compacted):
                skipped += 1
                continue
            updated += 1
            saved += len(original.encode("utf-8")) - len(compacted.encode("utf-8"))

        result = "Compacted" if apply else "Would compact"
        self.stdout.write(
            f"{result} {updated:,} of {scanned:,} system prompts, "
            f"saving {saved:,} bytes of prompt text."
        )
        if skipped:
            self.stdout.write(f"Skipped {skipped:,} prompts changed during the scan.")
        if unrecognised:
            self.stdout.write(f"Left {unrecognised:,} unrecognised system prompts alone.")
        if not apply:
            self.stdout.write("Dry run. Use --apply to write the changes.")
