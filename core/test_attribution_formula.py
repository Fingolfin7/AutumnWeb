from datetime import datetime, timedelta, timezone as datetime_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.attribution import (
    hierarchy_child_credit,
)
from core.models import Projects, Sessions, SessionSubproject, SubProjects


UTC = datetime_timezone.utc


class AttributionFormulaTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="attribution-formula"
        )
        self.project = Projects.objects.create(
            user=self.user, name="Weighted Project"
        )
        self.sub_a = SubProjects.objects.create(
            user=self.user, parent_project=self.project, name="A"
        )
        self.sub_b = SubProjects.objects.create(
            user=self.user, parent_project=self.project, name="B"
        )
        self.sub_c = SubProjects.objects.create(
            user=self.user, parent_project=self.project, name="C"
        )

    def _session(self, offset_seconds, duration_seconds):
        start = datetime(2026, 1, 1, 9, tzinfo=UTC) + timedelta(
            seconds=offset_seconds
        )
        return Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=start,
            end_time=start + timedelta(seconds=duration_seconds),
            is_active=False,
        )

    def _link(self, session, subproject, allocation_bp):
        return SessionSubproject.objects.create(
            session=session,
            subproject=subproject,
            allocation_bp=allocation_bp,
        )


    def test_hierarchy_children_receive_link_credit_without_residual(self):
        session = self._session(0, 40)
        self._link(session, self.sub_a, 2500)

        rows = hierarchy_child_credit(Sessions.objects.filter(pk=session.pk))

        self.assertEqual(
            rows,
            [
                {
                    "subproject_id": self.sub_a.id,
                    "total_numerator": 40 * 1000000 * 2500,
                    "total": timedelta(seconds=10),
                }
            ],
        )
