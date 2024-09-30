import json
import zlib
import base64
from datetime import datetime, timedelta
from django.utils import timezone
from django.db.models import Min, Max
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from core.models import Projects, SubProjects, Sessions


def json_decompress(content: dict | str) -> dict:
    ZIPJSON_KEY = 'base64(zip(o))'

    if isinstance(content, str):
        try:
            content = json.loads(content)
        except Exception:
            raise RuntimeError("Could not interpret the contents")

    try:
        assert (content[ZIPJSON_KEY])
        assert (set(content.keys()) == {ZIPJSON_KEY})
    except Exception:
        return content

    try:
        content = zlib.decompress(base64.b64decode(content[ZIPJSON_KEY]))
    except RuntimeError:
        raise RuntimeError("Could not decode/unzip the contents")

    try:
        content = json.loads(content)
    except RuntimeError:
        raise RuntimeError("Could interpret the unzipped contents")

    return content


def session_exists(user, project, start_time, end_time, subproject_names, time_tolerance=timedelta(minutes=2)) -> bool:
    """
    Check if a session already exists in the database based on start and end time (with tolerance),
    subprojects, and session notes.

    :param user: User instance the session belongs to
    :param project: Project instance the session belongs to
    :param start_time: Start time of the session
    :param end_time: End time of the session
    :param subproject_names: List of subproject names for the session
    :param time_tolerance: Allowed time difference between existing session and new session
    :return: True if a matching session exists, False otherwise
    """
    # Ensure subproject names are case-insensitive during comparison
    subproject_names_lower = {name.lower() for name in subproject_names}

    # If end_time is earlier than start_time, adjust start_time (the days probably switched over at midnight)
    if end_time < start_time:
        start_time -= timedelta(days=1)

    matching_sessions = Sessions.objects.filter(
        user=user,
        project=project,
        start_time__range=(start_time - time_tolerance, start_time + time_tolerance),
        end_time__range=(end_time - time_tolerance, end_time + time_tolerance)
        # note=note # commented out to allow for note differences (e.g. typos and edits might occur)
    )

    for session in matching_sessions:
        session_subproject_names = {name.lower() for name in session.subprojects.values_list('name', flat=True)}
        if subproject_names_lower == session_subproject_names:
            return True

    return False


def sessions_get_earliest_latest(sessions) -> tuple[datetime, datetime]:
    """
    Get the earliest start time and latest end time from a queryset of sessions.

    :param sessions: Queryset of session instances
    :return: Tuple of earliest start time and latest end time
    """
    aggregated_times = sessions.aggregate(earliest_start=Min('start_time'), latest_end=Max('end_time'))
    return aggregated_times['earliest_start'], aggregated_times['latest_end']


# usage:  python manage.py import 'username' project_file.json --force/--merge --tolerance 0.5
# e.g.: python manage.py import kuda "C:\Users\User\Documents\Programming\Python\Autumn\Source\projects.json"
# --merge --tolerance 2

class Command(BaseCommand):
    help = 'Import data from projects.json'

    def add_arguments(self, parser):
        parser.add_argument('username', type=str, help='Username of the user to import the data for')
        parser.add_argument('filepath', type=str, help='Path to an Autumn project json file')
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
            project = Projects.objects.filter(name=project_name).first()

            if project:
                if options['force']:
                    Projects.objects.filter(name=project_name).delete()
                    project = None  # to ensure a fresh creation
                elif merge:
                    self.stdout.write(self.style.NOTICE(f"Merging new sessions and subprojects into '{project_name}'..."))
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
                    status=project_data['Status'],
                )
                project.save()

            # Import or merge subprojects
            for subproject_name, subproject_time in project_data['Sub Projects'].items():
                subproject_name_lower = subproject_name.lower()  # Ensure case-insensitive handling
                subproject, created = SubProjects.objects.get_or_create(
                    user=user,
                    name=subproject_name_lower,  # Always use lowercase when saving
                    parent_project=project,
                    defaults={
                        'start_date': project.start_date,
                        'last_updated': project.last_updated,
                        'total_time': 0.0,
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

            sessions = Sessions.objects.filter(project=project)
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
