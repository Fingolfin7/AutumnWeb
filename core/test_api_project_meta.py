from django.contrib.auth.models import User
from django.test import TestCase

from rest_framework.test import APIClient

from core.models import Context, Projects, Tag


class ProjectMetadataApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="meta-user", email="meta-user@example.com", password="testpass"
        )
        self.other_user = User.objects.create_user(
            username="other-meta-user",
            email="other-meta-user@example.com",
            password="testpass",
        )
        self.project = Projects.objects.create(user=self.user, name="Autumn Project")
        self.context = Context.objects.create(user=self.user, name="Work")
        self.old_tag = Tag.objects.create(user=self.user, name="Old")
        self.project.tags.add(self.old_tag)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_project_update_sets_description_context_and_clears_context(self):
        response = self.client.patch(
            "/api/project/update/?compact=false",
            {
                "project": "autumn project",
                "description": "Updated description",
                "context": "work",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["project"]["description"], "Updated description")
        self.assertEqual(response.json()["project"]["context"], "Work")
        self.project.refresh_from_db()
        self.assertEqual(self.project.context, self.context)

        clear_response = self.client.patch(
            "/api/project/update/?compact=false",
            {"project": "Autumn Project", "context": ""},
            format="json",
        )

        self.assertEqual(clear_response.status_code, 200)
        self.assertIsNone(clear_response.json()["project"]["context"])
        self.project.refresh_from_db()
        self.assertIsNone(self.project.context)

    def test_project_update_unknown_context_returns_available_names(self):
        response = self.client.patch(
            "/api/project/update/",
            {"project": "Autumn Project", "context": "Missing"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Work", response.json()["error"])

    def test_project_update_replaces_tags_and_creates_missing_tags(self):
        existing_tag = Tag.objects.create(user=self.user, name="Focus")

        response = self.client.patch(
            "/api/project/update/?compact=false",
            {
                "project": "Autumn Project",
                "tags": ["focus", "New Tag"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["project"]["tags"], ["Focus", "New Tag"])
        self.assertEqual(
            list(self.project.tags.order_by("name").values_list("name", flat=True)),
            ["Focus", "New Tag"],
        )
        self.assertTrue(Tag.objects.filter(user=self.user, name="New Tag").exists())

    def test_create_project_accepts_context_and_tags(self):
        response = self.client.post(
            "/api/create_project/",
            {"name": "Created", "context": "work", "tags": ["Planning", "New"]},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["context"], "Work")
        self.assertEqual(response.json()["tags"], ["New", "Planning"])
        project = Projects.objects.get(user=self.user, name="Created")
        self.assertEqual(project.context, self.context)
        self.assertEqual(
            list(project.tags.order_by("name").values_list("name", flat=True)),
            ["New", "Planning"],
        )

    def test_context_create_duplicate_patch_and_delete(self):
        created = self.client.post(
            "/api/contexts/",
            {"name": "Study", "description": "Learning"},
            format="json",
        )

        self.assertEqual(created.status_code, 201)
        context_id = created.json()["context"]["id"]
        duplicate = self.client.post(
            "/api/contexts/", {"name": "study"}, format="json"
        )
        self.assertEqual(duplicate.status_code, 400)

        patched = self.client.patch(
            f"/api/contexts/{context_id}/?compact=false",
            {"name": "Research", "description": "Deep work"},
            format="json",
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.json()["context"]["name"], "Research")
        self.assertEqual(patched.json()["context"]["description"], "Deep work")

        context = Context.objects.get(pk=context_id)
        self.project.context = context
        self.project.save(update_fields=["context"])
        deleted = self.client.delete(f"/api/contexts/{context_id}/")
        self.assertEqual(deleted.status_code, 204)
        self.project.refresh_from_db()
        self.assertIsNone(self.project.context)

    def test_tag_create_patch_and_delete(self):
        created = self.client.post(
            "/api/tags/", {"name": "Urgent", "color": "#f00"}, format="json"
        )

        self.assertEqual(created.status_code, 201)
        tag_id = created.json()["tag"]["id"]
        patched = self.client.patch(
            f"/api/tags/{tag_id}/?compact=false",
            {"name": "Important", "color": "red"},
            format="json",
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.json()["tag"]["name"], "Important")
        self.assertEqual(patched.json()["tag"]["color"], "red")

        deleted = self.client.delete(f"/api/tags/{tag_id}/")
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(Tag.objects.filter(pk=tag_id).exists())

    def test_user_isolation_for_context_tag_and_project(self):
        other_context = Context.objects.create(user=self.other_user, name="Private")
        other_tag = Tag.objects.create(user=self.other_user, name="Secret")
        Projects.objects.create(user=self.other_user, name="Private Project")

        context_response = self.client.patch(
            f"/api/contexts/{other_context.id}/", {"name": "Nope"}, format="json"
        )
        tag_response = self.client.delete(f"/api/tags/{other_tag.id}/")
        project_response = self.client.patch(
            "/api/project/update/",
            {"project": "Private Project", "description": "Nope"},
            format="json",
        )

        self.assertEqual(context_response.status_code, 404)
        self.assertEqual(tag_response.status_code, 404)
        self.assertEqual(project_response.status_code, 404)
