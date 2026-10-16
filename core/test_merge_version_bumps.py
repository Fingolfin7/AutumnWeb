from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Projects, Sessions
from core.services.destructive import DestructiveMutationService


class MergeProjectsIfMatchInvalidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="merge-ifmatch", email="merge-ifmatch@example.com"
        )
        self.project1 = Projects.objects.create(user=self.user, name="Project A")
        self.project2 = Projects.objects.create(user=self.user, name="Project B")

        now = timezone.now()
        self.session = Sessions.objects.create(
            user=self.user,
            project=self.project1,
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
        )

        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_project_merge_invalidates_stale_if_match(self):
        read = self.client.get(
            reverse("api_v2:session-detail", args=[self.session.id])
        )
        self.assertEqual(read.status_code, 200)
        stale_version = read.json()["version"]

        DestructiveMutationService.merge_projects(
            user=self.user,
            project1_name="Project A",
            project2_name="Project B",
            new_project_name="Merged Project",
        )

        response = self.client.patch(
            reverse("api_v2:session-detail", args=[self.session.id]),
            {"note": "stale write"},
            format="json",
            HTTP_IF_MATCH=str(stale_version),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "version_conflict")
