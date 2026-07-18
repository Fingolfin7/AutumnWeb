from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class RemoveLegacyAllocationModeMigrationTests(TransactionTestCase):
    migrate_from = ("core", "0047_remove_sessions_core_sessio_user_id_509018_idx_and_more")
    migrate_to = ("core", "0048_remove_sessions_allocation_mode")

    def test_legacy_multilink_is_even_split_and_partitioned_is_untouched(self):
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps
        User = old_apps.get_model("auth", "User")
        Projects = old_apps.get_model("core", "Projects")
        SubProjects = old_apps.get_model("core", "SubProjects")
        Sessions = old_apps.get_model("core", "Sessions")
        SessionSubproject = old_apps.get_model("core", "SessionSubproject")

        user = User.objects.create(username="migration-0048")
        project = Projects.objects.create(user=user, name="Project")
        subprojects = [
            SubProjects.objects.create(
                user=user, parent_project=project, name=f"Sub {index}"
            )
            for index in range(3)
        ]
        legacy = Sessions.objects.create(
            user=user, project=project, allocation_mode="legacy_full"
        )
        partitioned = Sessions.objects.create(
            user=user, project=project, allocation_mode="partitioned"
        )
        for subproject in subprojects:
            SessionSubproject.objects.create(
                session=legacy, subproject=subproject, allocation_bp=10000
            )
        for subproject, bp in zip(subprojects, (2000, 3000, 4000)):
            SessionSubproject.objects.create(
                session=partitioned, subproject=subproject, allocation_bp=bp
            )

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        new_apps = executor.loader.project_state([self.migrate_to]).apps
        Link = new_apps.get_model("core", "SessionSubproject")
        self.assertEqual(
            list(
                Link.objects.filter(session_id=legacy.pk)
                .order_by("subproject_id")
                .values_list("allocation_bp", flat=True)
            ),
            [3334, 3333, 3333],
        )
        self.assertEqual(
            list(
                Link.objects.filter(session_id=partitioned.pk)
                .order_by("subproject_id")
                .values_list("allocation_bp", flat=True)
            ),
            [2000, 3000, 4000],
        )
