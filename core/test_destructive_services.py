from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.test import Client, TestCase
from django.urls import reverse

from core.models import Commitment, Projects


class DestructiveMutationAdminTests(TestCase):
    def test_admin_delete_of_targeted_project_is_blocked(self):
        admin_user = User.objects.create_superuser(
            username="destructive-admin",
            email="destructive-admin@example.com",
            password="testpass",
        )
        project = Projects.objects.create(user=admin_user, name="Admin Protected")
        commitment = Commitment.objects.create(
            user=admin_user,
            aggregation_type="project",
            project=project,
            target=60,
        )
        client = Client()
        client.force_login(admin_user)

        response = client.post(
            reverse("admin:core_projects_delete", args=[project.pk]),
            {"post": "yes"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Projects.objects.filter(pk=project.pk).exists())
        self.assertTrue(Commitment.objects.filter(pk=commitment.pk).exists())
        self.assertIn(
            "A commitment targets project 'Admin Protected'. "
            "Re-point or delete that commitment first.",
            [str(message) for message in get_messages(response.wsgi_request)],
        )
