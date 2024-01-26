import json
from datetime import datetime
from django.utils import timezone
from django.core.management.base import BaseCommand, CommandError
from core.models import Projects, SubProjects, Sessions


# usage:  python manage.py import project_file.json
class Command(BaseCommand):
    help = 'Import data from projects.json'

    def add_arguments(self, parser):
        parser.add_argument('filepath', type=str, help='Path to an Autumn project json file')

    def handle(self, *args, **options):
        filepath = options['filepath']
        self.stdout.write(f'Reading data from {filepath}...')

        try:
            with open(filepath) as f:
                data = json.load(f)
        except FileNotFoundError:
            raise CommandError(f'File not found: {filepath}')
        except json.JSONDecodeError:
            raise CommandError(f'Invalid JSON file: {filepath}')

        for project_name, project_data in data.items():
            self.stdout.write(f"Importing '{project_name}'...")
            project = Projects.objects.create(
                name=project_name,
                start_date=timezone.make_aware(datetime.strptime(project_data['Start Date'], '%m-%d-%Y')),
                last_updated=timezone.make_aware(datetime.strptime(project_data['Last Updated'], '%m-%d-%Y')),
                total_time=project_data['Total Time'],
                status=project_data['Status'],
            )
            project.save()

            for subproject_name, subproject_time in project_data['Sub Projects'].items():
                subproject = SubProjects.objects.create(
                    name=subproject_name,
                    start_date=project.start_date,
                    last_updated=project.last_updated,
                    total_time=subproject_time,
                    parent_project=project,
                )
                subproject.save()

            for session_data in project_data['Session History']:
                session = Sessions.objects.create(
                    project=project,
                    start_time=timezone.make_aware(
                        datetime.strptime(f"{session_data['Date']} {session_data['Start Time']}",
                                          '%m-%d-%Y %H:%M:%S')
                    ),
                    end_time=timezone.make_aware(
                        datetime.strptime(f"{session_data['Date']} {session_data['End Time']}",
                                          '%m-%d-%Y %H:%M:%S')
                    ),
                    is_active=False,
                    note=session_data['Note'],
                )

                for subproject_name in session_data['Sub-Projects']:
                    try:
                        subproject = SubProjects.objects.get(name=subproject_name)
                    except SubProjects.DoesNotExist:
                        raise CommandError(f'Sub-project not found: {subproject_name}')
                    session.subprojects.add(subproject)

                session.save()

        self.stdout.write(self.style.SUCCESS('Data imported successfully!'))
