from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import Projects, Sessions, SubProjects
from core.services import SessionMutationService
from core.totals import derived_project_totals, derived_subproject_totals


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

    def project_total(self, project=None):
        project = project or self.project
        return derived_project_totals(self.user, [project.pk])[project.pk]

    def subproject_total(self, subproject=None):
        subproject = subproject or self.subproject
        return derived_subproject_totals(
            self.user, [subproject.pk]
        )[subproject.pk]

    def test_active_completed_active_transitions_adjust_once(self):
        start = timezone.now() - timedelta(minutes=40)
        session = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            subprojects=[self.subproject],
            start_time=start,
            is_active=True,
        )

        self.assertEqual(self.project_total(), 0)
        self.assertEqual(self.subproject_total(), 0)

        session = SessionMutationService.mutate_session(
            session.pk,
            user=self.user,
            end_time=start + timedelta(minutes=40),
            is_active=False,
        )
        self.assertAlmostEqual(self.project_total(), 40, places=2)
        self.assertAlmostEqual(self.subproject_total(), 40, places=2)

        SessionMutationService.mutate_session(
            session.pk,
            user=self.user,
            end_time=None,
            is_active=True,
        )
        self.assertEqual(self.project_total(), 0)
        self.assertEqual(self.subproject_total(), 0)

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

        self.assertAlmostEqual(self.project_total(), 25, places=2)
        self.assertEqual(self.subproject_total(), 0)


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
