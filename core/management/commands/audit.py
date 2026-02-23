from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
import logging

from core.audit import audit_project_totals_all_users, audit_project_totals_for_user

logger = logging.getLogger("models")


class Command(BaseCommand):
    help = (
        "Audit project and subproject total time values. "
        "Use --username/--user-id for a single user, or --all for the full database."
    )

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
        log_per_item = not options["quiet"]

        if options["username"]:
            try:
                user = User.objects.get(username=options["username"])
            except User.DoesNotExist as exc:
                logger.error("User not found: %s", options["username"])
                raise CommandError(f'User not found: {options["username"]}') from exc

            self.stdout.write(f"Auditing project data for user: {user.username}")
            logger.info("Auditing project data for user: %s", user.username)
            project_count, subproject_count = audit_project_totals_for_user(user, log=log_per_item)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully audited user={user.username}: "
                    f"projects={project_count}, subprojects={subproject_count}"
                )
            )
            return

        if options["user_id"]:
            try:
                user = User.objects.get(pk=options["user_id"])
            except User.DoesNotExist as exc:
                logger.error("User not found: id=%s", options["user_id"])
                raise CommandError(f'User not found: id={options["user_id"]}') from exc

            self.stdout.write(f"Auditing project data for user id={user.id} ({user.username})")
            logger.info("Auditing project data for user id=%s (%s)", user.id, user.username)
            project_count, subproject_count = audit_project_totals_for_user(user, log=log_per_item)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully audited user={user.username}: "
                    f"projects={project_count}, subprojects={subproject_count}"
                )
            )
            return

        # Default path and explicit --all path both audit everything
        self.stdout.write("Auditing all project data")
        logger.info("Auditing all project data")
        user_count, project_count, subproject_count = audit_project_totals_all_users(log=log_per_item)
        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully audited full db: users={user_count}, "
                f"projects={project_count}, subprojects={subproject_count}"
            )
        )
