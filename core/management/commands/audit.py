from django.core.management.base import BaseCommand


DEPRECATION_MESSAGE = (
    "Deprecated: totals are always derived from sessions now; "
    "there is nothing to audit."
)


class Command(BaseCommand):
    help = "Deprecated compatibility command; totals are always derived."

    def add_arguments(self, parser):
        target_group = parser.add_mutually_exclusive_group()
        target_group.add_argument("--username", type=str, help="Audit one user by username")
        target_group.add_argument("--user-id", type=int, help="Audit one user by numeric id")
        target_group.add_argument(
            "--all",
            action="store_true",
            help="Audit all users (full database). This is also the default when no target is provided.",
        )
        parser.add_argument(
            "--quiet",
            action="store_true",
            help="Reduce per-project logging noise while still reporting summary output.",
        )

    def handle(self, *args, **options):
        self.stdout.write(DEPRECATION_MESSAGE)
