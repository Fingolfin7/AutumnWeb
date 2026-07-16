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







    def test_healthz_requires_no_authentication(self):
        client = APIClient()

        response = client.get("/healthz/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
