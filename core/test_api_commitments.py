from django.contrib.auth.models import User
from django.test import TestCase

from rest_framework.test import APIClient

from core.models import Commitment, Projects, SubProjects


class CommitmentApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="commit-api", email="commit-api@example.com", password="testpass"
        )
        self.other_user = User.objects.create_user(
            username="other-api", email="other-api@example.com", password="testpass"
        )
        self.project = Projects.objects.create(user=self.user, name="AutumnWeb")
        self.subproject = SubProjects.objects.create(
            user=self.user,
            parent_project=self.project,
            name="API",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _project_payload(self, **overrides):
        payload = {
            "aggregation_type": "project",
            "target": "AutumnWeb",
            "target_value": 120,
        }
        payload.update(overrides)
        return payload

    def test_list_includes_full_progress(self):
        Commitment.objects.create(user=self.user, project=self.project, target=120)

        response = self.client.get("/api/commitments/?compact=false")

        self.assertEqual(response.status_code, 200)
        item = response.json()["commitments"][0]
        self.assertEqual(item["target_name"], "AutumnWeb")
        self.assertIn("progress", item)
        self.assertIn("actual", item["progress"])
        self.assertIn("percentage", item["progress"])
        self.assertIn("status", item["progress"])

    def test_create_project_target_and_duplicate_target(self):
        response = self.client.post(
            "/api/commitments/", self._project_payload(), format="json"
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["commitment"]["target_name"], "AutumnWeb")

        duplicate = self.client.post(
            "/api/commitments/", self._project_payload(), format="json"
        )
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("already has a commitment", duplicate.json()["error"])

    def test_create_subproject_target(self):
        response = self.client.post(
            "/api/commitments/",
            {
                "aggregation_type": "subproject",
                "target": "API",
                "project": "AutumnWeb",
                "target_value": 3,
                "commitment_type": "sessions",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()["commitment"]
        self.assertEqual(payload["aggregation_type"], "subproject")
        self.assertEqual(payload["target_name"], "API")

    def test_patch_target_value(self):
        commitment = Commitment.objects.create(user=self.user, project=self.project, target=120)

        response = self.client.patch(
            f"/api/commitments/{commitment.id}/",
            {"target_value": 240},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["commitment"]["target"], 240)
        commitment.refresh_from_db()
        self.assertEqual(commitment.target, 240)

    def test_delete_commitment(self):
        commitment = Commitment.objects.create(user=self.user, project=self.project, target=120)

        response = self.client.delete(f"/api/commitments/{commitment.id}/")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Commitment.objects.filter(pk=commitment.pk).exists())

    def test_user_isolation(self):
        commitment = Commitment.objects.create(user=self.user, project=self.project, target=120)
        self.client.force_authenticate(self.other_user)

        list_response = self.client.get("/api/commitments/")
        detail_response = self.client.get(f"/api/commitments/{commitment.id}/")

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json()["commitments"], [])
        self.assertEqual(detail_response.status_code, 404)

    def test_healthz_requires_no_authentication(self):
        client = APIClient()

        response = client.get("/healthz/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
