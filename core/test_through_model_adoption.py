from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from core.models import Projects, Sessions, SessionSubproject, SubProjects
from core.services import SessionMutationService


class SessionSubprojectAdoptionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='through-adoption')
        self.project = Projects.objects.create(user=self.user, name='Project')
        self.first = SubProjects.objects.create(
            user=self.user,
            name='First',
            parent_project=self.project,
        )
        self.second = SubProjects.objects.create(
            user=self.user,
            name='Second',
            parent_project=self.project,
        )

    def test_service_creation_uses_even_allocation(self):
        session = SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            subprojects=[self.first, self.second],
            is_active=True,
        )

        session.refresh_from_db()
        self.assertEqual(
            list(
                SessionSubproject.objects.filter(session=session)
                .order_by('subproject_id')
                .values_list('allocation_bp', flat=True)
            ),
            [5000, 5000],
        )

    def test_add_uses_full_allocation_and_check_rejects_out_of_range_values(self):
        session = Sessions.objects.create(user=self.user, project=self.project)
        session.subprojects.add(self.first)

        link = SessionSubproject.objects.get(session=session, subproject=self.first)
        self.assertEqual(link.allocation_bp, 10000)

        with self.assertRaises(IntegrityError), transaction.atomic():
            SessionSubproject.objects.create(
                session=session,
                subproject=self.second,
                allocation_bp=0,
            )

        with self.assertRaises(IntegrityError), transaction.atomic():
            SessionSubproject.objects.filter(pk=link.pk).update(allocation_bp=10001)

    def test_duplicate_session_subproject_pair_is_rejected(self):
        session = Sessions.objects.create(user=self.user, project=self.project)
        SessionSubproject.objects.create(session=session, subproject=self.first)

        with self.assertRaises(IntegrityError), transaction.atomic():
            SessionSubproject.objects.create(session=session, subproject=self.first)
