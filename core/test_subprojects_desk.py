"""Tests for the Focus Desk subproject pages (UI_REDESIGN.md chunk 5)."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Context, Projects, SubProjects


class SubprojectPagesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="finrod", email="finrod@example.com", password="pw"
        )
        self.context = Context.objects.create(user=self.user, name="Work")
        self.atlas = Projects.objects.create(
            user=self.user, name="Atlas API", context=self.context
        )
        self.auth = SubProjects.objects.create(
            user=self.user, parent_project=self.atlas, name="auth"
        )
        SubProjects.objects.create(
            user=self.user, parent_project=self.atlas, name="billing"
        )
        self.client.login(username="finrod", password="pw")

    def test_every_subproject_page_uses_the_focus_desk_shell_only(self):
        pages = [
            reverse("create_subproject", args=[self.atlas.id]),
            reverse("update_subproject", args=[self.auth.id]),
            reverse("delete_subproject", args=[self.auth.id]),
            reverse("merge_subprojects", args=[self.atlas.id]),
        ]

        for url in pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "core/base.html")
                self.assertContains(response, "core/css/focus_desk.css")
                self.assertNotContains(response, "core/css/style.css")

    def test_each_page_links_back_to_its_parent_project(self):
        """A subproject page is meaningless without saying whose it is."""
        parent_url = reverse("update_project", args=[self.atlas.id])

        for url in (
            reverse("update_subproject", args=[self.auth.id]),
            reverse("delete_subproject", args=[self.auth.id]),
            reverse("merge_subprojects", args=[self.atlas.id]),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, parent_url)
                self.assertContains(response, "Atlas API")

    def test_the_create_form_keeps_its_hidden_parent_field(self):
        response = self.client.get(reverse("create_subproject", args=[self.atlas.id]))

        self.assertContains(response, 'name="parent_project"')
