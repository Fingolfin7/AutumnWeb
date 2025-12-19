import json
import os
from datetime import datetime
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from AutumnWeb import settings
from core.models import Projects
from core.utils import json_compress


class Command(BaseCommand):
    help = 'Export data from database to a JSON file.'

    def add_arguments(self, parser):
        parser.add_argument('username', type=str, help='Username of the user to import the data for')
        parser.add_argument('--output_file', type=str, help='Path to an Autumn project json file')
        parser.add_argument('--project', type=str, help='Project name to export')
        parser.add_argument('--compress', action='store_true', help='Compress the output JSON file')
        parser.add_argument('--autumn_compatible', action='store_true', help='Print verbose output')

    def handle(self, *args, **options):
        # Fetch the user
        try:
            user = User.objects.get(username=options['username'])
        except User.DoesNotExist:
            raise CommandError(f"User '{options['username']}' does not exist")

        # Build base queryset with related data to avoid N+1 queries
        base_qs = Projects.objects.filter(user=user).select_related("context").prefetch_related(
            "tags",
            "subprojects",
            "sessions",
        )
        if options["project"]:
            projects = base_qs.filter(name=options["project"])
        else:
            projects = base_qs

        if options['output_file']:
            filepath = os.path.join(settings.BASE_DIR, "Exports", options['output_file'])
        else:
            if options['project']:
                filepath = os.path.join(settings.BASE_DIR, "Exports", f"{options['project']}.json")
            else:
                filepath = os.path.join(settings.BASE_DIR, "Exports",
                                        f"Export_{datetime.now().strftime('%m-%d-%Y_%H-%M-%S')}.json")

        if not os.path.exists(os.path.dirname(filepath)):
            os.makedirs(os.path.dirname(filepath))

        if not filepath.endswith('.json'):
            filepath += '.json'

        autumn_compatible = options['autumn_compatible']

        project_data = {}

        for project in projects:
            # For each project, collect its details
            project.audit_total_time()  # Ensure the total time is up-to-date
            project_name = project.name
            start_date = timezone.localtime(project.start_date)
            last_updated = timezone.localtime(project.last_updated)
            project_obj = {
                'Start Date': start_date.strftime('%m-%d-%Y'),
                'Last Updated': last_updated.strftime('%m-%d-%Y'),
                'Total Time': project.total_time,
                'Status': project.status,
                'Description': project.description if project.description else '',
                'Sub Projects': {},
                'Session History': [],
            }

            if not autumn_compatible:
                project_obj["Context"] = project.context.name if project.context else ""
                project_obj["Tags"] = [t.name for t in project.tags.all()]

            # Fetch related subprojects
            subprojects = project.subprojects.all()
            for subproject in subprojects:
                subproject.audit_total_time()
                subproject_name = subproject.name

                if autumn_compatible:
                    project_obj['Sub Projects'][subproject_name] = subproject.total_time
                else:
                    start_date = timezone.localtime(subproject.start_date)
                    last_updated = timezone.localtime(subproject.last_updated)
                    subproject_obj = {
                        'Start Date': start_date.strftime('%m-%d-%Y'),
                        'Last Updated': last_updated.strftime('%m-%d-%Y'),
                        'Total Time': subproject.total_time,
                        'Description': subproject.description if subproject.description else '',
                    }
                    project_obj['Sub Projects'][subproject_name] = subproject_obj

            # Fetch related sessions
            project_sessions = project.sessions.filter(is_active=False).all()
            for session in reversed(project_sessions):  # oldest to newest
                start_time = timezone.localtime(session.start_time)
                end_time = timezone.localtime(session.end_time)
                project_obj['Session History'].append({
                    'Date': end_time.strftime('%m-%d-%Y'),
                    'Start Time': start_time.strftime('%H:%M:%S'),
                    'End Time': end_time.strftime('%H:%M:%S'),
                    'Sub-Projects': [subproject.name for subproject in session.subprojects.all()],
                    'Duration': session.duration,
                    'Note': session.note if session.note else "",
                })

            project_data[project_name] = project_obj

        # Write the project data to a JSON file
        with open(filepath, 'w') as json_writer:
            if options['compress']:
                contents = json.dumps(json_compress(project_data))
                json_writer.write(contents)
            else:
                contents = json.dumps(project_data, indent=4)
                json_writer.write(contents)


        self.stdout.write(self.style.SUCCESS(f'Data successfully exported to {filepath}'))
