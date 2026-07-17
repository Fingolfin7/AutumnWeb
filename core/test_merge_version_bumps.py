from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Projects, Sessions, SessionSubproject, SubProjects
from core.services.destructive import DestructiveMutationService


class MergeProjectsVersionBumpTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="merge-proj", password="pw")
        self.project1 = Projects.objects.create(user=self.user, name="Project A")
        self.project2 = Projects.objects.create(user=self.user, name="Project B")

        now = timezone.now()
        self.session1 = Sessions.objects.create(
            user=self.user,
            project=self.project1,
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
        )
        self.session2 = Sessions.objects.create(
            user=self.user,
            project=self.project2,
            start_time=now - timedelta(hours=3),
            end_time=now - timedelta(hours=2),
        )

    def test_merge_projects_increments_every_surviving_session_version(self):
        original_versions = {
            self.session1.id: self.session1.version,
            self.session2.id: self.session2.version,
        }

        merged_project, _ = DestructiveMutationService.merge_projects(
            user=self.user,
            project1_name="Project A",
            project2_name="Project B",
            new_project_name="Merged Project",
        )

        surviving = list(merged_project.sessions.all())
        self.assertEqual(len(surviving), 2)
        for session in surviving:
            self.assertEqual(
                session.version, original_versions[session.id] + 1
            )


class MergeSubprojectsVersionBumpTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="merge-sub", password="pw")
        self.project = Projects.objects.create(user=self.user, name="Parent")
        self.subproject1 = SubProjects.objects.create(
            user=self.user, name="Design", parent_project=self.project
        )
        self.subproject2 = SubProjects.objects.create(
            user=self.user, name="UI", parent_project=self.project
        )

        now = timezone.now()
        self.session = Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
        )
        self.session.subprojects.add(self.subproject1, self.subproject2)

    def test_merge_subprojects_bumps_version_and_repoints_allocations(self):
        original_version = self.session.version

        merged_subproject = DestructiveMutationService.merge_subprojects(
            user=self.user,
            project_id=self.project.id,
            name1="Design",
            name2="UI",
            new_name="Design & UI",
        )

        self.session.refresh_from_db()
        self.assertEqual(self.session.version, original_version + 1)

        link_subproject_ids = list(
            SessionSubproject.objects.filter(session=self.session).values_list(
                "subproject_id", flat=True
            )
        )
        self.assertEqual(link_subproject_ids, [merged_subproject.id])


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
