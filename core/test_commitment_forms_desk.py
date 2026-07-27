"""Tests for the Focus Desk commitment forms (UI_REDESIGN.md chunk 7)."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Commitment, Context, Projects, SubProjects, Tag


class CommitmentFormPagesTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="finrod", email="finrod@example.com", password="pw"
        )
        self.context = Context.objects.create(user=self.user, name="Work")
        self.tag = Tag.objects.create(user=self.user, name="deep-work")
        self.project = Projects.objects.create(
            user=self.user, name="Atlas API", context=self.context
        )
        self.project.tags.add(self.tag)
        self.subproject = SubProjects.objects.create(
            user=self.user, parent_project=self.project, name="auth"
        )
        self.commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type="time",
            period="weekly",
            target=300,
        )
        self.client.login(username="finrod", password="pw")


class CommitmentShellTests(CommitmentFormPagesTestCase):
    def test_every_commitment_form_uses_the_focus_desk_shell_only(self):
        pages = [
            reverse("create_commitment_generic"),
            reverse("create_commitment", args=[self.project.id]),
            reverse("update_commitment", args=[self.commitment.id]),
        ]

        for url in pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "core/base_fd.html")
                self.assertContains(response, "core/css/focus_desk.css")
                self.assertNotContains(response, "core/css/style.css")


class ScriptContractTests(CommitmentFormPagesTestCase):
    """Every hook below is read by the inline script on both form pages."""

    def test_create_form_keeps_its_script_hooks(self):
        html = self.client.get(reverse("create_commitment_generic")).content.decode()
        self._assert_commitment_script_contract(html)

    def test_update_form_keeps_its_script_hooks(self):
        html = self.client.get(
            reverse("update_commitment", args=[self.commitment.id])
        ).content.decode()
        self._assert_commitment_script_contract(html)

    def _assert_commitment_script_contract(self, html):
        for hook in (
            'id="id_aggregation_type"',
            'id="scope-target-search"',
            'id="scope-target-options"',
            'id="id_commitment_type"',
            'id="id_target"',
            'id="id_context"',
            'id="id_tag"',
            'id="id_project"',
            'id="id_subproject"',
            'data-target-type="context"',
            'data-target-type="tag"',
            'data-target-type="project"',
            'data-target-type="subproject"',
            'data-dimension="project"',
            'data-dimension="subproject"',
            'data-dimension="tag"',
        ):
            with self.subTest(hook=hook):
                self.assertIn(hook, html)

        for hook in (
            "commitment-target-field",
            "commitment-rule-group",
            "commitment-rule-dropdown",
            "commitment-rule-search",
            "commitment-rule-option",
            "tag-summary",
            "tag-label",
        ):
            with self.subTest(hook=hook):
                self.assertIn(hook, html)
