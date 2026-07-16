from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.models import Projects, Sessions, SubProjects
from core.services import SessionMutationService


class SessionMutationServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="ledger-user", password="password"
        )
        self.project = Projects.objects.create(
            user=self.user, name="Ledger Project"
        )
        self.subproject = SubProjects.objects.create(
            user=self.user,
            name="Ledger Subproject",
            parent_project=self.project,
        )

    def test_active_completed_active_transitions_adjust_once(self):
        start = timezone.now() - timedelta(minutes=40)
        session = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            subprojects=[self.subproject],
            start_time=start,
            is_active=True,
        )

        self.project.refresh_from_db()
        self.subproject.refresh_from_db()
        self.assertEqual(self.project.total_time, 0)
        self.assertEqual(self.subproject.total_time, 0)

        session = SessionMutationService.mutate_session(
            session.pk,
            user=self.user,
            end_time=start + timedelta(minutes=40),
            is_active=False,
        )
        self.project.refresh_from_db()
        self.subproject.refresh_from_db()
        self.assertAlmostEqual(self.project.total_time, 40, places=2)
        self.assertAlmostEqual(self.subproject.total_time, 40, places=2)

        SessionMutationService.mutate_session(
            session.pk,
            user=self.user,
            end_time=None,
            is_active=True,
        )
        self.project.refresh_from_db()
        self.subproject.refresh_from_db()
        self.assertEqual(self.project.total_time, 0)
        self.assertEqual(self.subproject.total_time, 0)

    def test_clearing_subprojects_only_removes_subproject_contribution(self):
        start = timezone.now() - timedelta(minutes=25)
        session = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            subprojects=[self.subproject],
            start_time=start,
            end_time=start + timedelta(minutes=25),
            is_active=False,
        )

        SessionMutationService.mutate_session(
            session.pk, user=self.user, subprojects=[]
        )

        self.project.refresh_from_db()
        self.subproject.refresh_from_db()
        self.assertAlmostEqual(self.project.total_time, 25, places=2)
        self.assertEqual(self.subproject.total_time, 0)

    def test_duration_edit_uses_atomic_delta_without_history_audit(self):
        start = timezone.now() - timedelta(minutes=30)
        session = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            subprojects=[self.subproject],
            start_time=start,
            end_time=start + timedelta(minutes=30),
            is_active=False,
        )

        with (
            patch.object(Projects, "audit_total_time") as project_audit,
            patch.object(SubProjects, "audit_total_time") as subproject_audit,
            CaptureQueriesContext(connection) as queries,
        ):
            SessionMutationService.mutate_session(
                session.pk,
                user=self.user,
                start_time=start - timedelta(minutes=15),
            )

        project_audit.assert_not_called()
        subproject_audit.assert_not_called()
        sql = [query["sql"] for query in queries.captured_queries]
        project_updates = [
            statement
            for statement in sql
            if 'UPDATE "core_projects"' in statement
            and '"total_time"' in statement
        ]
        self.assertTrue(project_updates)
        self.assertTrue(
            any('"total_time" +' in statement for statement in project_updates)
        )
        self.assertFalse(
            any(
                'FROM "core_sessions"' in statement
                and 'WHERE "core_sessions"."project_id"' in statement
                for statement in sql
            )
        )

        self.project.refresh_from_db()
        self.subproject.refresh_from_db()
        self.assertAlmostEqual(self.project.total_time, 45, places=2)
        self.assertAlmostEqual(self.subproject.total_time, 45, places=2)

    def test_rejects_subprojects_from_a_different_project(self):
        other_project = Projects.objects.create(
            user=self.user, name="Other Ledger Project"
        )
        other_subproject = SubProjects.objects.create(
            user=self.user,
            name="Other Ledger Subproject",
            parent_project=other_project,
        )

        with self.assertRaises(ValidationError):
            SessionMutationService.create_session(
                user=self.user,
                project=self.project,
                subprojects=[other_subproject],
                start_time=timezone.now() - timedelta(minutes=5),
                end_time=timezone.now(),
                is_active=False,
            )

        self.assertFalse(Sessions.objects.filter(project=self.project).exists())

    def test_direct_note_save_does_not_change_cached_contribution(self):
        start = timezone.now() - timedelta(minutes=10)
        session = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=start,
            end_time=start + timedelta(minutes=10),
            is_active=False,
        )

        session.note = "No contribution fields changed"
        session.save()

        self.project.refresh_from_db()
        self.assertAlmostEqual(self.project.total_time, 10, places=2)
        self.assertEqual(Sessions.objects.filter(pk=session.pk).count(), 1)
