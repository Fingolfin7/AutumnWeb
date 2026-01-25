from datetime import datetime
from django.apps import AppConfig
from apscheduler.schedulers.background import BackgroundScheduler
from django.conf import settings
import logging
import os

logger = logging.getLogger("models")


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

        if os.environ.get("RUN_MAIN") == "true" and settings.RUN_AUDIT_SCHEDULER:
            from core.models import Projects, SubProjects, Sessions

            scheduler = BackgroundScheduler(timezone=settings.TIME_ZONE)

            def periodic_audits():
                """Run periodic audits on all projects and subprojects"""
                logger.info("Running audits on all projects and subprojects")
                projects = Projects.objects.all()
                for project in projects:
                    project.audit_total_time(log=False)
                    for subproject in SubProjects.objects.filter(
                        parent_project=project
                    ):
                        subproject.audit_total_time(log=False)
                logger.info("Finished audits on projects and subprojects")

            # run every hour
            scheduler.add_job(
                periodic_audits,
                "interval",
                hours=settings.AUDIT_PERIOD,
                id="periodic_audits",
                misfire_grace_time=60,
                # if the job is missed within a 60-second window, it will still run
                max_instances=1,  # only one instance of the job can run at a time
                replace_existing=True,  # if the job is already running, replace it with the new one
                next_run_time=datetime.now(),
            )

            scheduler.start()
            logger.info("Audit scheduler started")
