from pathlib import Path

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction

from core.services.account_backup import RestoreConflict, preview_backup, restore_backup, validate_backup
from core.services.backup_archive import archive_digest, read_archive
from core.services.backup_records import BackupError


class Command(BaseCommand):
    help = "Recover an account from an Autumn ZIP in the database configured for this installation."
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument("username", help="Destination username on this installation.")
        parser.add_argument("archive", type=Path, help="Path to a downloaded Autumn account ZIP.")
        parser.add_argument(
            "--create-user", metavar="EMAIL",
            help="Create the destination with this email and an unusable password.",
        )
        parser.add_argument("--apply", action="store_true", help="Apply the restore. The default is a preview.")

    def handle(self, *, username, archive, create_user, apply, **options):
        try:
            with archive.open("rb") as source:
                upload = File(source, name=archive.name)
                digest = archive_digest(upload)
                with read_archive(upload) as reader:
                    manifest = validate_backup(reader)
                    self.restore(username, create_user, apply, reader, manifest, digest)
        except (BackupError, RestoreConflict, OSError) as error:
            raise CommandError(str(error)) from error

    def restore(self, username, email, apply, reader, manifest, digest):
        with transaction.atomic():
            user = User.objects.filter(username=username).first()
            created = user is None
            if user is None:
                if email is None:
                    raise CommandError("Destination account does not exist. Supply --create-user EMAIL to create it.")
                user = self.create_destination(username, email)

            report = preview_backup(user, manifest, digest)
            self.stdout.write(f"Backup from {report['source_account']} into {report['destination_account']}.")
            for section, counts in report["counts"].items():
                if any(counts.values()):
                    self.stdout.write(
                        f"  {section}: {counts['add']} to restore, {counts['identical']} identical, "
                        f"{counts['conflict']} conflicts."
                    )
            if not report["can_restore"]:
                for conflict in report["conflicts"]:
                    self.stderr.write(f"  {conflict['section']}: {conflict['label']}")
                raise CommandError("Resolve conflicts in the destination before restoring.")

            if not apply:
                transaction.set_rollback(True)
                self.stdout.write("Preview only. Run with --apply to restore.")
                return

            result = restore_backup(user, manifest, reader, digest=digest, token=report["preview_token"])
        self.stdout.write(self.style.SUCCESS(f"Restored {result['restored']} record(s) into {username}."))
        if created:
            self.stdout.write(f"Set a new password with manage.py changepassword {username}.")

    @staticmethod
    def create_destination(username, email):
        try:
            validate_email(email)
            user = User(username=username, email=User.objects.normalize_email(email))
            user.set_unusable_password()
            user.full_clean()
            user.save()
        except (ValidationError, IntegrityError) as error:
            raise CommandError(f"Could not create destination account: {error}") from error
        return user
