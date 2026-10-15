from unittest import mock

from django.contrib import admin
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from freezegun import freeze_time
from rest_framework.test import APIClient

from core.admin import CommitmentAdmin
from core.models import Commitment, Projects
from core.services import CommitmentEditService


class CommitmentWriteClosureTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="closure-user", password="testpass"
        )
        self.project = Projects.objects.create(user=self.user, name="Closure")

    @freeze_time("2026-01-01 12:00:00+00:00")
    def test_api_next_boundary_edit_queues_and_marks_dirty(self):
        # The React commitment form edits through PATCH /api/v2/commitments/{id};
        # it must go through the same CommitmentEditService write closure the
        # old page did: a pending revision, a version bump, and a recompute.
        commitment = CommitmentEditService.create(
            self.user,
            {"aggregation_type": "project", "project": self.project, "target": 60},
        )
        client = APIClient()
        client.force_authenticate(self.user)

        # The response reads the commitment back and reconciles it, which would
        # clear the dirty flag; hold the recompute off so the flag the edit set shows.
        with mock.patch("core.commitments.recompute_commitment"):
            response = client.patch(
                reverse("api_v2:commitment-detail", args=[commitment.pk]),
                {"target_value": 90},
                format="json",
                HTTP_IF_MATCH=str(commitment.version),
            )

        self.assertEqual(response.status_code, 200, response.content)
        commitment.refresh_from_db()
        self.assertEqual(commitment.target, 60)
        self.assertEqual(commitment.revisions.get(status="pending").target_value, 90)
        self.assertEqual(commitment.version, 2)
        self.assertTrue(commitment.needs_recompute)
        self.assertEqual(response.json()["version"], 2)
        self.assertEqual(response.json()["pending_revision"]["changes"], {"target_value": 90})

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
