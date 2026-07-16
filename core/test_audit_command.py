from datetime import timedelta
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core.models import Projects, Sessions, SubProjects


DEPRECATION_MESSAGE = (
    "Deprecated: totals are always derived from sessions now; "
    "there is nothing to audit."
)


class AuditDeprecationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="audit-user", password="x")
        self.project = Projects.objects.create(
            user=self.user, name="Audit Project", total_time=999
        )
        self.subproject = SubProjects.objects.create(
            user=self.user,
            parent_project=self.project,
            name="Audit Subproject",
            total_time=999,
        )

        end = timezone.now()
        session = Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=end - timedelta(minutes=30),
            end_time=end,
            is_active=False,
        )
        session.subprojects.add(self.subproject)

    def test_command_accepts_legacy_arguments_and_exits_successfully(self):
        argument_sets = (
            ("--username", self.user.username, "--quiet"),
            ("--user-id", str(self.user.id), "--quiet"),
            ("--all", "--quiet"),
            (),
        )
        for arguments in argument_sets:
            with self.subTest(arguments=arguments):
                stdout = StringIO()
                result = call_command("audit", *arguments, stdout=stdout)
                self.assertIsNone(result)
                self.assertEqual(stdout.getvalue(), DEPRECATION_MESSAGE + "\n")

        self.project.refresh_from_db()
        self.subproject.refresh_from_db()
        self.assertEqual(self.project.total_time, 999)
        self.assertEqual(self.subproject.total_time, 999)

    def test_endpoint_ignores_dry_run_and_returns_deprecation_contract(self):
        self.client.force_login(self.user)

        response = self.client.post(
            "/api/audit/",
            data={"dry_run": True},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "ok": True,
                "deprecated": True,
                "message": DEPRECATION_MESSAGE,
            },
        )
        self.project.refresh_from_db()
        self.subproject.refresh_from_db()
        self.assertEqual(self.project.total_time, 999)
        self.assertEqual(self.subproject.total_time, 999)
