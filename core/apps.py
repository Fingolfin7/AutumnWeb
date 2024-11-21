from datetime import datetime
from django.apps import AppConfig
from apscheduler.schedulers.background import BackgroundScheduler
from django.conf import settings
import logging
import os

# log to screen
logger = logging.getLogger('django')


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        if os.environ.get('RUN_MAIN') == 'true': # run the ready method (and therefore the scheduler) only once
            import core.signals
            from core.models import Projects, SubProjects, Sessions
            scheduler = BackgroundScheduler(timezone=settings.TIME_ZONE)

            def periodic_audits():
                """Run periodic audits on all projects and subprojects"""
                logger.info("Running audits on all projects and subprojects")
                projects = Projects.objects.all()
                for project in projects:
                    project.audit_total_time(log=False)
                    for subproject in SubProjects.objects.filter(parent_project=project):
                        subproject.audit_total_time(log=False)
                logger.info("Finished audits on projects and subprojects")

            # run every hour
            scheduler.add_job(periodic_audits, 'interval', hours=1,
                              id='periodic_audits',
                              misfire_grace_time=60,
                              # if the job is missed within a 60-second window, it will still run
                              max_instances=1,  # only one instance of the job can run at a time
                              replace_existing=True,  # if the job is already running, replace it with the new one
                              next_run_time=datetime.now())

            scheduler.start()
