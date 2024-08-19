import json
import zlib
import base64
from datetime import datetime, timedelta
from django.utils import timezone
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


# usage:  python manage.py import project_file.json --force --tolerance 0.5
class Command(BaseCommand):
    help = 'Import data from projects.json'

    def add_arguments(self, parser):
        parser.add_argument('filepath', type=str, help='Path to an Autumn project json file')
        parser.add_argument('--force', action='store_true', help='Force import even if projects already exist')
        parser.add_argument('--tolerance', type=float, default=0.5, help='Tolerance for total time mismatch in minutes'
                                                                         'due to rounding errors '
                                                                         '(default 0.5)')

    def handle(self, *args, **options):
        filepath = options['filepath']
        tolerance = options['tolerance']

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
            if Projects.objects.filter(name=project_name).exists():
                if options['force']:
                    Projects.objects.filter(name=project_name).delete()
                else:
                    skipped.append(project_name)
                    continue

            self.stdout.write(f"Importing '{project_name}'...")
            project = Projects.objects.create(
                name=project_name,
                start_date=timezone.make_aware(datetime.strptime(project_data['Start Date'], '%m-%d-%Y')),
                last_updated=timezone.make_aware(datetime.strptime(project_data['Last Updated'], '%m-%d-%Y')),
                total_time=0.0,  # no need to read in total time because it will be recalculated with the sessions saves
                status=project_data['Status'],
            )
            project.save()

            for subproject_name, subproject_time in project_data['Sub Projects'].items():
                subproject = SubProjects.objects.create(
                    name=subproject_name,
                    start_date=project.start_date,
                    last_updated=project.last_updated,
                    total_time=0.0,
                    # no need to read in total time because it will be recalculated with the sessions saves
                    parent_project=project,
                )
                subproject.save()

            for session_data in project_data['Session History']:
                start_time = timezone.make_aware(
                    datetime.strptime(f"{session_data['Date']} {session_data['Start Time']}",
                                      '%m-%d-%Y %H:%M:%S')
                )
                end_time = timezone.make_aware(
                    datetime.strptime(f"{session_data['Date']} {session_data['End Time']}",
                                      '%m-%d-%Y %H:%M:%S')
                )

                # Check if end_time is earlier than start_time
                if end_time < start_time:
                    # If so, subtract one day from start_time
                    start_time -= timedelta(days=1)

                session = Sessions.objects.create(
                    project=project,
                    start_time=start_time,
                    end_time=end_time,
                    is_active=False,
                    note=session_data['Note'],
                )

                for subproject_name in session_data['Sub-Projects']:
                    try:
                        subproject = SubProjects.objects.get(name=subproject_name, parent_project=project)
                    except SubProjects.DoesNotExist:
                        raise CommandError(f'Sub-project not found: {subproject_name}')
                    session.subprojects.add(subproject)

                session.save()

            # compare the total time read in from the file to the total time calculated from the sessions

            # run audits on the project and subprojects
            project.audit_total_time()
            for subproject in project.subprojects.all():
                subproject.audit_total_time()

            mismatch = abs(project.total_time - project_data['Total Time'])
            if mismatch > tolerance:  # allow for rounding errors in totals
                # delete the project that hit the mismatch
                tally = project.total_time
                project.delete()
                raise CommandError(f"Total time mismatch for project '{project_name}': "
                                   f"expected {project_data['Total Time']}, got {tally}. "
                                   f"Mismatch: {mismatch}")


        #

        self.stdout.write(self.style.SUCCESS('Data imported successfully!'))

        if len(skipped) > 0:
            self.stdout.write(self.style.WARNING(f'Skipped the following projects '
                                                 f'as they already exist in the database:'))
            for num, project_name in enumerate(skipped):
                self.stdout.write(f'{num}. {project_name}{", " if num < len(skipped) - 1 else ""}')
