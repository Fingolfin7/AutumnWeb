"""Tests for the Focus Desk projects pages (UI_REDESIGN.md chunk 4)."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Context, Projects, SubProjects, Tag


class ProjectsPageTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="finrod", email="finrod@example.com", password="pw"
        )
        self.context = Context.objects.create(user=self.user, name="Work")
        self.tag = Tag.objects.create(user=self.user, name="deep-work")
        self.atlas = Projects.objects.create(
            user=self.user, name="Atlas API", context=self.context
        )
        self.atlas.tags.add(self.tag)
        self.paused = Projects.objects.create(
            user=self.user, name="Old Thing", context=self.context, status="paused"
        )
        self.client.login(username="finrod", password="pw")


class ProjectsShellTests(ProjectsPageTestCase):
    def test_every_project_page_uses_the_focus_desk_shell_only(self):
        sub = SubProjects.objects.create(
            user=self.user, parent_project=self.atlas, name="auth"
        )
        pages = [
            reverse("projects"),
            reverse("create_project"),
            reverse("update_project", args=[self.atlas.id]),
            reverse("delete_project", args=[self.atlas.id]),
            reverse("merge_projects"),
        ]

        for url in pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "core/base.html")
                self.assertContains(response, "core/css/focus_desk.css")
                self.assertNotContains(response, "core/css/style.css")

        self.assertTrue(SubProjects.objects.filter(pk=sub.pk).exists())

    def test_non_active_groups_start_closed_in_the_markup(self):
        """Closed-on-load must be markup, not a script: the legacy page
        collapsed these with jQuery after paint, which flashed them open."""
        html = self.client.get(reverse("projects")).content.decode()

        active = html.split('<span class="disclose-title">Active</span>')[0]
        paused = html.split('<span class="disclose-title">Paused</span>')[0]

        self.assertNotIn("is-closed", active.rsplit("<section", 1)[-1])
        self.assertIn("is-closed", paused.rsplit("<section", 1)[-1])

    def test_filters_are_echoed_on_the_projects_page_too(self):
        response = self.client.get(
            reverse("projects"), {"context": str(self.context.id)}
        )

        self.assertIn(
            {"label": "Context", "value": "Work"}, response.context["active_filters"]
        )
        self.assertContains(response, "filter-pill")

    def test_a_project_row_can_start_a_timer_by_post(self):
        """The row's primary action must not be a GET link — starting a timer
        is a mutation."""
        response = self.client.get(reverse("projects"))

        self.assertContains(response, 'action="{}"'.format(reverse("start_timer")))
        self.assertContains(response, 'name="project" value="Atlas API"')
        self.assertContains(response, "project-start")

    def test_the_empty_list_distinguishes_no_data_from_no_matches(self):
        Projects.objects.filter(user=self.user).delete()

        no_data = self.client.get(reverse("projects"))
        self.assertContains(no_data, "No projects yet")

        Projects.objects.create(user=self.user, name="Something")
        no_matches = self.client.get(reverse("projects"), {"project_name": "zzz"})
        self.assertContains(no_matches, "No projects match these filters")
