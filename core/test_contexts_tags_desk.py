"""Tests for the Focus Desk context and tag pages (UI_REDESIGN.md chunk 8)."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Context, Tag


class ContextsTagsPageTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="elrond", email="elrond@example.com", password="pw"
        )
        self.context = Context.objects.create(
            user=self.user, name="Council", description="Work in Rivendell"
        )
        self.tag = Tag.objects.create(
            user=self.user, name="urgent", color="#d18b4c"
        )
        self.client.login(username="elrond", password="pw")


class ContextsTagsShellTests(ContextsTagsPageTestCase):
    def test_every_context_and_tag_page_uses_the_focus_desk_shell_only(self):
        pages = [
            reverse("contexts"),
            reverse("update_context", args=[self.context.id]),
            reverse("delete_context", args=[self.context.id]),
            reverse("tags"),
            reverse("update_tag", args=[self.tag.id]),
            reverse("delete_tag", args=[self.tag.id]),
        ]

        for url in pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "core/base.html")
                self.assertContains(response, "core/css/focus_desk.css")
                self.assertNotContains(response, "core/css/style.css")

    def test_edit_pages_link_back_to_their_list_pages(self):
        context_response = self.client.get(
            reverse("update_context", args=[self.context.id])
        )
        tag_response = self.client.get(reverse("update_tag", args=[self.tag.id]))

        self.assertContains(context_response, 'href="{}"'.format(reverse("contexts")))
        self.assertContains(tag_response, 'href="{}"'.format(reverse("tags")))

    def test_contexts_empty_state_links_to_the_create_form(self):
        Context.objects.filter(user=self.user).delete()

        response = self.client.get(reverse("contexts"))

        self.assertContains(response, "No contexts yet")
        self.assertContains(response, 'href="#create-context"')

    def test_tags_empty_state_links_to_the_create_form(self):
        Tag.objects.filter(user=self.user).delete()

        response = self.client.get(reverse("tags"))

        self.assertContains(response, "No tags yet")
        self.assertContains(response, 'href="#create-tag"')
