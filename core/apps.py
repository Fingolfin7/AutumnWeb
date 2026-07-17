from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        import core.signals  # make sure signals are imported and therefore run

        # NOTE: Temporarily disabled DB-touching initialization.
        # We previously enabled WAL mode for SQLite here:
        #   PRAGMA journal_mode=WAL;
        # Running database PRAGMAs from AppConfig.ready() can interfere with
        # management commands, migrations, and recovery.
        # Reintroduce later with a safe guard if needed.
        #
        # from django.db import connection
        # if connection.vendor == "sqlite":
        #     with connection.cursor() as cursor:
        #         cursor.execute("PRAGMA journal_mode=WAL;")
