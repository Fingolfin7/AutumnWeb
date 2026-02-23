from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core.models import Projects, Sessions, SubProjects


class AuditCommandTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="audit-user", password="x")
        self.project = Projects.objects.create(user=self.user, name="Audit Project", total_time=999)
        self.subproject = SubProjects.objects.create(
            user=self.user,
            parent_project=self.project,
            name="Audit Subproject",
            total_time=999,
        )

        start = timezone.now() - timedelta(minutes=30)
        end = timezone.now()
        session = Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=start,
            end_time=end,
            is_active=False,
        )
        session.subprojects.add(self.subproject)

    def test_audit_command_for_single_user_by_username(self):
        call_command("audit", "--username", self.user.username, "--quiet")

        self.project.refresh_from_db()
        self.subproject.refresh_from_db()
        self.assertAlmostEqual(self.project.total_time, 30, places=1)
        self.assertAlmostEqual(self.subproject.total_time, 30, places=1)

    def test_audit_command_for_single_user_by_id(self):
        call_command("audit", "--user-id", str(self.user.id), "--quiet")

        self.project.refresh_from_db()
        self.assertAlmostEqual(self.project.total_time, 30, places=1)

    def test_audit_command_all(self):
        call_command("audit", "--all", "--quiet")

        self.project.refresh_from_db()
        self.assertAlmostEqual(self.project.total_time, 30, places=1)
