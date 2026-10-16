
from django.contrib import admin
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from core.admin import CommitmentAdmin
from core.models import Commitment, Projects
from core.services import CommitmentEditService


class CommitmentWriteClosureTests(TestCase):
    def test_admin_definition_fields_are_readonly_and_submission_cannot_change(self):
        superuser = User.objects.create_superuser(
            username="closure-admin", password="testpass", email="admin@example.com"
        )
        project = Projects.objects.create(user=superuser, name="Admin Closure")
        commitment = CommitmentEditService.create(
            superuser,
            {"aggregation_type": "project", "project": project, "target": 60},
        )
        model_admin = admin.site._registry[Commitment]
        self.assertIsInstance(model_admin, CommitmentAdmin)
        for field in (
            "aggregation_type",
            "project",
            "commitment_type",
            "period",
            "target",
            "banking_enabled",
            "active",
            "balance",
            "needs_recompute",
            "ledger_start_at",
            "generation",
            "version",
        ):
            self.assertIn(field, model_admin.readonly_fields)
        self.assertEqual(model_admin.list_editable, ())

        client = Client()
        client.login(username=superuser.username, password="testpass")
        response = client.post(
            reverse("admin:core_commitment_change", args=[commitment.pk]),
            {"target": 999, "_save": "Save"},
        )
        self.assertEqual(response.status_code, 302)
        commitment.refresh_from_db()
        self.assertEqual(commitment.target, 60)
        self.assertEqual(commitment.version, 1)
