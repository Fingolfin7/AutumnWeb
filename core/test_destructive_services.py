from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Commitment, Context, Projects, Sessions, SubProjects, Tag


class DestructiveMutationApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="destructive-user",
            email="destructive@example.com",
            password="testpass",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def make_commitment(self, *, kind, target, active=True):
        return Commitment.objects.create(
            user=self.user,
            aggregation_type=kind,
            target=60,
            active=active,
            **{kind: target},
        )

    def test_project_delete_rejects_targeted_project_without_changes(self):
        project = Projects.objects.create(user=self.user, name="Protected")
        commitment = self.make_commitment(
            kind="project", target=project, active=False
        )
        message = (
            "A commitment targets project 'Protected'. "
            "Re-point or delete that commitment first."
        )

        response = self.client.delete(
            reverse("api_delete_project", args=[project.name])
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"error": message})
        self.assertTrue(Projects.objects.filter(pk=project.pk).exists())
        self.assertTrue(Commitment.objects.filter(pk=commitment.pk).exists())

    def test_project_merge_rejects_when_either_side_is_targeted(self):
        for index, targeted_side in enumerate((1, 2), start=1):
            with self.subTest(targeted_side=targeted_side):
                project1 = Projects.objects.create(
                    user=self.user, name=f"Project A{index}"
                )
                project2 = Projects.objects.create(
                    user=self.user, name=f"Project B{index}"
                )
                targeted = project1 if targeted_side == 1 else project2
                commitment = self.make_commitment(
                    kind="project", target=targeted
                )
                merged_name = f"Merged {index}"
                message = (
                    f"A commitment targets project '{targeted.name}'. "
                    "Re-point or delete that commitment first."
                )

                response = self.client.post(
                    reverse("api_merge_projects"),
                    {
                        "project1": project1.name,
                        "project2": project2.name,
                        "new_project_name": merged_name,
                    },
                    format="json",
                )

                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json(), {"error": message})
                self.assertTrue(Projects.objects.filter(pk=project1.pk).exists())
                self.assertTrue(Projects.objects.filter(pk=project2.pk).exists())
                self.assertFalse(
                    Projects.objects.filter(
                        user=self.user, name=merged_name
                    ).exists()
                )
                self.assertTrue(
                    Commitment.objects.filter(pk=commitment.pk).exists()
                )

    def test_subproject_delete_rejects_targeted_subproject_without_changes(self):
        project = Projects.objects.create(user=self.user, name="Parent")
        subproject = SubProjects.objects.create(
            user=self.user, parent_project=project, name="Protected Sub"
        )
        session = Sessions.objects.create(
            user=self.user, project=project, is_active=True
        )
        session.subprojects.add(subproject)
        commitment = self.make_commitment(
            kind="subproject", target=subproject, active=False
        )
        message = (
            "A commitment targets subproject 'Protected Sub'. "
            "Re-point or delete that commitment first."
        )

        response = self.client.delete(
            reverse(
                "api_delete_subproject", args=[project.name, subproject.name]
            )
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"error": message})
        self.assertTrue(SubProjects.objects.filter(pk=subproject.pk).exists())
        self.assertTrue(Commitment.objects.filter(pk=commitment.pk).exists())
        self.assertTrue(session.subprojects.filter(pk=subproject.pk).exists())

    def test_subproject_merge_rejects_targeted_subproject_without_changes(self):
        project = Projects.objects.create(user=self.user, name="Merge Parent")
        subproject1 = SubProjects.objects.create(
            user=self.user, parent_project=project, name="A"
        )
        subproject2 = SubProjects.objects.create(
            user=self.user, parent_project=project, name="B"
        )
        commitment = self.make_commitment(
            kind="subproject", target=subproject2
        )
        message = (
            "A commitment targets subproject 'B'. "
            "Re-point or delete that commitment first."
        )

        response = self.client.post(
            reverse("api_merge_subprojects"),
            {
                "project_id": project.pk,
                "subproject1": "A",
                "subproject2": "B",
                "new_subproject_name": "M",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"error": message})
        self.assertTrue(SubProjects.objects.filter(pk=subproject1.pk).exists())
        self.assertTrue(SubProjects.objects.filter(pk=subproject2.pk).exists())
        self.assertFalse(
            SubProjects.objects.filter(parent_project=project, name="M").exists()
        )
        self.assertTrue(Commitment.objects.filter(pk=commitment.pk).exists())

    def test_project_and_subproject_renames_keep_target_commitments(self):
        project = Projects.objects.create(user=self.user, name="Old Project")
        project_commitment = self.make_commitment(
            kind="project", target=project
        )
        parent = Projects.objects.create(user=self.user, name="Parent Rename")
        subproject = SubProjects.objects.create(
            user=self.user, parent_project=parent, name="Old Sub"
        )
        subproject_commitment = self.make_commitment(
            kind="subproject", target=subproject
        )

        project_response = self.client.post(
            reverse("api_rename"),
            {
                "type": "project",
                "project": "Old Project",
                "new_name": "New Project",
            },
            format="json",
        )
        subproject_response = self.client.post(
            reverse("api_rename"),
            {
                "type": "subproject",
                "project": "Parent Rename",
                "subproject": "Old Sub",
                "new_name": "New Sub",
            },
            format="json",
        )

        self.assertEqual(project_response.status_code, 200)
        self.assertEqual(subproject_response.status_code, 200)
        project.refresh_from_db()
        subproject.refresh_from_db()
        project_commitment.refresh_from_db()
        subproject_commitment.refresh_from_db()
        self.assertEqual(project.name, "New Project")
        self.assertEqual(subproject.name, "New Sub")
        self.assertEqual(project_commitment.project_id, project.pk)
        self.assertEqual(subproject_commitment.subproject_id, subproject.pk)

    def test_untargeted_subproject_delete_detaches_session_link(self):
        project = Projects.objects.create(user=self.user, name="Delete Parent")
        subproject = SubProjects.objects.create(
            user=self.user, parent_project=project, name="Disposable"
        )
        session = Sessions.objects.create(
            user=self.user,
            project=project,
            start_time=timezone.now(),
            is_active=True,
        )
        session.subprojects.add(subproject)

        response = self.client.delete(
            reverse(
                "api_delete_subproject", args=[project.name, subproject.name]
            )
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(SubProjects.objects.filter(pk=subproject.pk).exists())
        self.assertTrue(Sessions.objects.filter(pk=session.pk).exists())
        self.assertEqual(session.subprojects.count(), 0)

    def test_context_and_tag_delete_reject_target_commitments(self):
        context = Context.objects.create(user=self.user, name="Protected Context")
        tag = Tag.objects.create(user=self.user, name="Protected Tag")
        context_commitment = self.make_commitment(kind="context", target=context)
        tag_commitment = self.make_commitment(kind="tag", target=tag)

        context_response = self.client.delete(
            reverse("api_context_detail", args=[context.pk])
        )
        tag_response = self.client.delete(
            reverse("api_tag_detail", args=[tag.pk])
        )

        self.assertEqual(context_response.status_code, 409)
        self.assertEqual(
            context_response.json(),
            {
                "error": "A commitment targets context 'Protected Context'. "
                "Re-point or delete that commitment first."
            },
        )
        self.assertEqual(tag_response.status_code, 409)
        self.assertEqual(
            tag_response.json(),
            {
                "error": "A commitment targets tag 'Protected Tag'. "
                "Re-point or delete that commitment first."
            },
        )
        self.assertTrue(Context.objects.filter(pk=context.pk).exists())
        self.assertTrue(Tag.objects.filter(pk=tag.pk).exists())
        self.assertTrue(
            Commitment.objects.filter(pk=context_commitment.pk).exists()
        )
        self.assertTrue(Commitment.objects.filter(pk=tag_commitment.pk).exists())


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
