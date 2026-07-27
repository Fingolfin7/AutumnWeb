"""Tests for the Focus Desk import and export pages (UI_REDESIGN.md chunk 10)."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Context, Projects, Tag


class ImportExportShellTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="finrod", password="pw")
        context = Context.objects.create(user=self.user, name="Work")
        tag = Tag.objects.create(user=self.user, name="deep-work")
        project = Projects.objects.create(
            user=self.user, name="Atlas API", context=context
        )
        project.tags.add(tag)
        self.client.login(username="finrod", password="pw")

    def test_import_and_export_use_the_focus_desk_shell_only(self):
        for url in (reverse("import"), reverse("export")):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "core/base_fd.html")
                self.assertContains(response, "core/css/focus_desk.css")
                self.assertNotContains(response, "core/css/style.css")
