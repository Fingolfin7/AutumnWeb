from django.core.management.base import BaseCommand, CommandError

from core.services.notification_retention import cleanup_notification_history


class Command(BaseCommand):
    help = "Delete old terminal notification history in a bounded batch."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=None)
        parser.add_argument("--batch-size", type=int, default=None)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if options["days"] is not None and options["days"] < 0:
            raise CommandError("--days cannot be negative.")
        if options["batch_size"] is not None and not 1 <= options["batch_size"] <= 1000:
            raise CommandError("--batch-size must be between 1 and 1000.")
        count = cleanup_notification_history(
            retention_days=options["days"],
            batch_size=options["batch_size"],
            dry_run=options["dry_run"],
        )
        action = "would delete" if options["dry_run"] else "deleted"
        self.stdout.write(self.style.SUCCESS(f"Notification history: {action} {count} event(s)."))
