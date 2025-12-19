import json
from datetime import datetime, timedelta
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from core.models import Projects, SubProjects, Sessions, status_choices
from core.utils import (
    json_decompress,
    session_exists,
    sessions_get_earliest_latest,
    apply_context_and_tags_to_project,
)


# usage:  python manage.py import 'username' project_file.json --force/--merge --tolerance 0.5
# e.g.: python manage.py import kuda "C:\Users\User\Documents\Programming\Python\Autumn\Source\projects.json"
# --merge --tolerance 2


class Command(BaseCommand):
    help = 'Import data from projects.json'

    def add_arguments(self, parser):
        parser.add_argument('username', type=str, help='Username of the user to import the data for')
        parser.add_argument('filepath', type=str, help='Path to an Autumn project json file')
        parser.add_argument('--autumn_import', action='store_true', help='Import data in Autumn (CLI version) format')
        parser.add_argument('--force', action='store_true', help='Force import even if projects already exist')
        parser.add_argument('--merge', action='store_true',
                            help='Merge sessions and subprojects into existing projects')
        parser.add_argument('--tolerance', type=float, default=0.5, help='Tolerance for total time mismatch in minutes'
                                                                         'due to rounding errors '
                                                                         '(default 0.5)')
        parser.add_argument('--verbose', action='store_true', help='Print verbose output')

    def handle(self, *args, **options):
        filepath = options['filepath']
        tolerance = options['tolerance']
        merge = options['merge']
        verbose = options['verbose']

        # check if the user exists
        try:
            user = User.objects.get(username=options['username'])
        except User.DoesNotExist:
            raise CommandError(f'User not found: {options["username"]}')

        self.stdout.write(f'Reading data from {filepath}...')
        skipped = []

        try:
            with open(filepath) as f:
                try:  # import compressed json
                    data = json_decompress(f.read())
                except RuntimeError:
                    data = json.load(f)

        except FileNotFoundError:
            raise CommandError(f'File not found: {filepath}')
        except json.JSONDecodeError:
            raise CommandError(f'Invalid JSON file: {filepath}')

        for project_name, project_data in data.items():
            project = Projects.objects.filter(name=project_name, user=user).first()

            if project:
                if options['force']:
                    Projects.objects.filter(name=project_name, user=user).delete()
                    project = None  # to ensure a fresh creation
                elif merge:
                    self.stdout.write(
                        self.style.NOTICE(f"Merging new sessions and subprojects into '{project_name}'..."))
                else:
                    skipped.append(project_name)
                    continue

            if not project:
                self.stdout.write(self.style.NOTICE(f"Importing '{project_name}'..."))
                project = Projects.objects.create(
                    user=user,
                    name=project_name,
                    start_date=timezone.make_aware(datetime.strptime(project_data['Start Date'], '%m-%d-%Y')),
                    last_updated=timezone.make_aware(datetime.strptime(project_data['Last Updated'], '%m-%d-%Y')),
                    total_time=0.0,
                    description=project_data['Description'] if 'Description' in project_data else '',
                )

                if 'Status' in project_data:  # handle old versions from before the status field was added
                    # Find the status tuple that matches the project_data['Status']
                    status_tuple = next(
                        (status for status in status_choices if status[0] == project_data['Status']), None)

                    if status_tuple:
                        project.status = status_tuple[0]
                    else:
                        raise ValueError(f"Invalid status: {project_data['Status']}")
                project.save()

                # Apply context/tags (merge-aware, backwards compatible)
                apply_context_and_tags_to_project(
                    user=user,
                    project=project,
                    project_data=project_data,
                    merge=bool(merge and Projects.objects.filter(
                        name=project_name,
                        user=user,
                    ).exists()),
                )

            # Import or merge subprojects
            for subproject_name, subproject_time in project_data['Sub Projects'].items():
                subproject_name_lower = subproject_name.lower()  # Ensure case-insensitive handling
                if options['autumn_import']:
                    subproject, created = SubProjects.objects.get_or_create(
                        user=user,
                        name=subproject_name_lower,
                        parent_project=project,
                        defaults={  # these values aren't used in the search. But they are added to new instances
                            'start_date': project.start_date,
                            'last_updated': project.last_updated,
                            'total_time': 0.0,
                            'description': '',
                        }
                    )
                else:
                    subproject, created = SubProjects.objects.get_or_create(
                        user=user,
                        name=subproject_name_lower,
                        parent_project=project,
                        defaults={  # these values aren't used in the search. But they are added to new instances
                            "start_date": timezone.make_aware(
                                datetime.strptime(project_data['Sub Projects'][subproject_name]['Start Date'],
                                                  '%m-%d-%Y')),
                            "last_updated": timezone.make_aware(
                                datetime.strptime(project_data['Sub Projects'][subproject_name]['Last Updated'],
                                                  '%m-%d-%Y')),
                            "description": project_data['Sub Projects'][subproject_name]['Description']
                            if 'Description' in project_data['Sub Projects'][subproject_name] else '',
                        }
                    )
                if created and verbose:
                    self.stdout.write(f"Created new subproject '{subproject_name}' under project '{project_name}'.")

            # Import or merge session history
            for session_data in project_data['Session History']:
                start_time = timezone.make_aware(
                    datetime.strptime(f"{session_data['Date']} {session_data['Start Time']}", '%m-%d-%Y %H:%M:%S')
                )
                end_time = timezone.make_aware(
                    datetime.strptime(f"{session_data['Date']} {session_data['End Time']}", '%m-%d-%Y %H:%M:%S')
                )

                subproject_names = [name.lower() for name in session_data['Sub-Projects']]  # Convert to lowercase
                note = session_data['Note']

                # If end_time is earlier than start_time,
                # adjust start_time (the days probably switched over at midnight)
                if end_time < start_time:
                    start_time -= timedelta(days=1)

                # Check if the session already exists
                if session_exists(user, project, start_time, end_time, subproject_names,
                                  time_tolerance=timedelta(minutes=tolerance)):
                    continue

                if verbose:
                    self.stdout.write(
                        f"Importing session on {session_data['Date']} from {session_data['Start Time']} to "
                        f"{session_data['End Time']}...")

                session = Sessions.objects.create(
                    user=user,
                    project=project,
                    start_time=start_time,
                    end_time=end_time,
                    is_active=False,
                    note=note,
                )

                for subproject_name in subproject_names:
                    try:
                        subproject = SubProjects.objects.get(user=user, name=subproject_name, parent_project=project)
                    except SubProjects.DoesNotExist:
                        raise CommandError(f'Subproject not found: {subproject_name}')
                    session.subprojects.add(subproject)

                session.save()

            # Run audits on the project and subprojects
            project.audit_total_time()
            for subproject in project.subprojects.all():
                subproject.audit_total_time()

            sessions = Sessions.objects.filter(project=project, user=user)
            earliest_start, latest_end = sessions_get_earliest_latest(sessions)

            # Update project and subproject dates if merging
            if merge and earliest_start and latest_end:
                project.start_date = earliest_start
                project.last_updated = latest_end
                project.save()

                # Update subprojects' start and last updated dates
                for subproject in project.subprojects.all():
                    earliest_start, latest_end = sessions_get_earliest_latest(subproject.sessions.all())
                    subproject.start_date = earliest_start if earliest_start else project.start_date
                    subproject.last_updated = latest_end if latest_end else project.last_updated
                    subproject.save()

            if not merge:
                mismatch = abs(project.total_time - project_data['Total Time'])
                if mismatch > tolerance:
                    tally = project.total_time
                    project.delete()
                    raise CommandError(f"Total time mismatch for project '{project_name}': "
                                       f"expected {project_data['Total Time']}, got {tally}. "
                                       f"Mismatch: {mismatch}")

        self.stdout.write(self.style.SUCCESS('Data imported successfully!'))

        if len(skipped) > 0:
            self.stdout.write(self.style.WARNING(f'Skipped the following projects '
                                                 f'as they already exist in the database:'))
            for num, project_name in enumerate(skipped):
                self.stdout.write(f'{num}. {project_name}{", " if num < len(skipped) - 1 else ""}')
