import copy
import json
import os
import tempfile
from datetime import timedelta
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from core.importer import run_import
from core.models import Context, Projects, Sessions, SubProjects
from core.services import SessionMutationService


def format_one_payload():
    return {
        'Client Work': {
            'Start Date': '01-02-2024',
            'Last Updated': '01-02-2024',
            'Total Time': 60.0,
            'Status': 'active',
            'Description': 'Imported work',
            'Context': 'Exported Context',
            'Tags': ['important'],
            'Sub Projects': {
                'Planning': {
                    'Start Date': '01-02-2024',
                    'Last Updated': '01-02-2024',
                    'Total Time': 60.0,
                    'Description': 'Planning work',
                }
            },
            'Session History': [
                {
                    'Date': '01-02-2024',
                    'Start Time': '09:00:00',
                    'End Time': '10:00:00',
                    'Sub-Projects': ['Planning'],
                    'Note': 'First import',
                }
            ],
        }
    }


class SessionUuidTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='session-uuid', password='password'
        )
        self.project = Projects.objects.create(
            user=self.user, name='UUID Project'
        )

    def test_service_creates_distinct_non_null_uuids(self):
        start = timezone.now().replace(microsecond=0) - timedelta(hours=2)
        first = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=start,
            end_time=start + timedelta(minutes=30),
            is_active=False,
        )
        second = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=start + timedelta(hours=1),
            end_time=start + timedelta(hours=1, minutes=30),
            is_active=False,
        )

        self.assertIsNotNone(first.uuid)
        self.assertIsNotNone(second.uuid)
        self.assertNotEqual(first.uuid, second.uuid)

    def test_user_and_uuid_are_unique_together(self):
        first = Sessions.objects.create(
            user=self.user, project=self.project, is_active=True
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            Sessions.objects.create(
                user=self.user,
                project=self.project,
                uuid=first.uuid,
                is_active=True,
            )

    def test_timer_start_and_track_create_internal_uuids(self):
        self.client.force_login(self.user)
        timer_start = timezone.now().replace(microsecond=0) - timedelta(hours=4)
        timer_response = self.client.post(
            '/api/timer/start/',
            data=json.dumps(
                {'project': self.project.name, 'start': timer_start.isoformat()}
            ),
            content_type='application/json',
        )
        self.assertEqual(timer_response.status_code, 201)
        self.assertNotIn('uuid', timer_response.json()['session'])
        timer = Sessions.objects.get(pk=timer_response.json()['session']['id'])
        self.assertIsNotNone(timer.uuid)

        track_start = timer_start + timedelta(hours=2)
        track_response = self.client.post(
            '/api/track/',
            data=json.dumps(
                {
                    'project': self.project.name,
                    'start': track_start.isoformat(),
                    'end': (track_start + timedelta(hours=1)).isoformat(),
                }
            ),
            content_type='application/json',
        )
        self.assertEqual(track_response.status_code, 201)
        self.assertNotIn('uuid', track_response.json()['session'])
        tracked = Sessions.objects.get(
            pk=track_response.json()['session']['id']
        )
        self.assertIsNotNone(tracked.uuid)

    def test_importer_creates_non_null_uuid(self):
        run_import(self.user, format_one_payload(), tolerance=0.5)

        self.assertIsNotNone(Sessions.objects.get(user=self.user).uuid)


class ImportCommandConsolidationTests(TestCase):
    def setUp(self):
        self.command_user = User.objects.create_user(
            username='command-import', email='command-import@example.com'
        )
        self.shared_user = User.objects.create_user(
            username='shared-import', email='shared-import@example.com'
        )

    def write_payload(self, payload):
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8'
        ) as import_file:
            json.dump(payload, import_file)
            filepath = import_file.name
        self.addCleanup(lambda: os.path.exists(filepath) and os.unlink(filepath))
        return filepath

    def call_import(self, user, payload, *args, **options):
        filepath = self.write_payload(payload)
        output = StringIO()
        call_command(
            'import', user.username, filepath, *args, stdout=output, **options
        )
        return output.getvalue()

    def database_state(self, user):
        projects = []
        for project in Projects.objects.filter(user=user).order_by('name'):
            subprojects = []
            for subproject in project.subprojects.order_by('name'):
                subprojects.append(
                    (
                        subproject.name,
                        subproject.start_date,
                        subproject.last_updated,
                        subproject.total_time,
                        subproject.description,
                    )
                )
            sessions = []
            for session in project.sessions.order_by('start_time'):
                sessions.append(
                    (
                        session.start_time,
                        session.end_time,
                        session.note,
                        session.is_active,
                        tuple(
                            session.subprojects.order_by('name').values_list(
                                'name', flat=True
                            )
                        ),
                    )
                )
            projects.append(
                (
                    project.name,
                    project.start_date,
                    project.last_updated,
                    project.total_time,
                    project.status,
                    project.description,
                    project.context.name,
                    tuple(project.tags.order_by('name').values_list('name', flat=True)),
                    tuple(subprojects),
                    tuple(sessions),
                )
            )
        return projects

    def test_command_matches_run_import_with_the_same_options(self):
        payload = format_one_payload()
        command_context = Context.objects.create(
            user=self.command_user, name='Selected Context'
        )
        shared_context = Context.objects.create(
            user=self.shared_user, name='Selected Context'
        )

        run_import(
            self.shared_user,
            copy.deepcopy(payload),
            tolerance=0.5,
            verbose=True,
            import_into_context=shared_context,
        )
        self.call_import(
            self.command_user,
            payload,
            tolerance=0.5,
            verbose=True,
            context=command_context.name,
        )

        self.assertEqual(
            self.database_state(self.command_user),
            self.database_state(self.shared_user),
        )

    def test_force_replaces_an_existing_project(self):
        payload = format_one_payload()
        self.call_import(self.command_user, payload)
        replacement = copy.deepcopy(payload)
        replacement['Client Work']['Session History'][0]['Note'] = 'Replacement'

        self.call_import(self.command_user, replacement, force=True)

        self.assertEqual(
            Projects.objects.filter(user=self.command_user, name='Client Work').count(),
            1,
        )
        session = Sessions.objects.get(user=self.command_user)
        self.assertEqual(session.note, 'Replacement')
        self.assertIsNotNone(session.uuid)

    def test_merge_adds_new_subprojects_and_sessions(self):
        payload = format_one_payload()
        self.call_import(self.command_user, payload)
        merged = copy.deepcopy(payload)
        merged_project = merged['Client Work']
        merged_project['Sub Projects']['Review'] = {
            'Start Date': '01-02-2024',
            'Last Updated': '01-02-2024',
            'Total Time': 30.0,
            'Description': 'Review work',
        }
        merged_project['Session History'] = [
            {
                'Date': '01-02-2024',
                'Start Time': '10:00:00',
                'End Time': '10:30:00',
                'Sub-Projects': ['Review'],
                'Note': 'Merged import',
            }
        ]
        merged_project['Total Time'] = 30.0

        self.call_import(self.command_user, merged, merge=True)

        self.assertEqual(Sessions.objects.filter(user=self.command_user).count(), 2)
        self.assertTrue(
            SubProjects.objects.filter(
                user=self.command_user, name='review'
            ).exists()
        )

    def test_total_time_mismatch_raises_command_error(self):
        payload = format_one_payload()
        payload['Client Work']['Total Time'] = 61.0
        filepath = self.write_payload(payload)

        with self.assertRaisesMessage(CommandError, 'Total time mismatch'):
            call_command(
                'import',
                self.command_user.username,
                filepath,
                stdout=StringIO(),
            )

        self.assertFalse(
            Projects.objects.filter(user=self.command_user, name='Client Work').exists()
        )
