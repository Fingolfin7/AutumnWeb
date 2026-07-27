from django.core.management.base import BaseCommand, CommandError

from core.temp_uploads import sweep, temp_upload_dir


class Command(BaseCommand):
    help = (
        "Remove abandoned import uploads staged under MEDIA_ROOT/temp. "
        "An upload is normally deleted once its import streams, so anything "
        "left here belongs to a session that walked away."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than-hours",
            type=float,
            default=24.0,
            help="Only remove uploads untouched for this long (default: 24).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be removed without deleting anything.",
        )

    def handle(self, *args, **options):
        hours = options["older_than_hours"]
        if hours < 0:
            raise CommandError("--older-than-hours cannot be negative")

        dry_run = options["dry_run"]
        removed, freed = sweep(max_age_seconds=hours * 3600, dry_run=dry_run)

        for path in removed:
            self.stdout.write(f"{'Would remove' if dry_run else 'Removed'} {path}")

        if not removed:
            self.stdout.write(
                f"No uploads older than {hours}h in {temp_upload_dir()}"
            )
            return

        verb = "would be freed" if dry_run else "freed"
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(removed)} upload(s), {freed / 1024:.1f} KB {verb}"
            )
        )
