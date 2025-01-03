from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from core.models import Projects, SubProjects
import logging

logger = logging.getLogger('models')


class Command(BaseCommand):
    help = 'Audit the total time for all projects and subprojects'

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, help='Username of the user to audit the data for')

    def handle(self, *args, **options):
        if options['username']:
            # check if the user exists
            try:
                user = User.objects.get(username=options['username'])
                self.stdout.write(f'Auditing project data for user: {user.username}')
                logger.info(f"Auditing project data for user: {user.username}")
                projects = Projects.objects.filter(user=user)
                for project in projects:
                    project.audit_total_time()
                    for subproject in SubProjects.objects.filter(parent_project=project, user=user):
                        subproject.audit_total_time()
            except User.DoesNotExist:
                logger.error(f'User not found: {options["username"]}')
                raise CommandError(f'User not found: {options["username"]}')
        else:
            self.stdout.write('Auditing all project data')
            logger.info("Auditing all project data")
            projects = Projects.objects.all()
            for project in projects:
                project.audit_total_time(log=False)
                for subproject in SubProjects.objects.filter(parent_project=project):
                    subproject.audit_total_time(log=False)

        self.stdout.write(self.style.SUCCESS('Successfully audited project data'))
        logger.info("Successfully audited project data")