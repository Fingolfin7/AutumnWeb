"""Tests for the Focus Desk charts page (UI_REDESIGN.md chunk 9).

charts/core.js reaches into this template by id. A renamed hook leaves the
page looking fine and drawing nothing, which no other test would catch.
"""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Context, Projects


class ChartsPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="finrod", email="finrod@example.com", password="pw"
        )
        self.context = Context.objects.create(user=self.user, name="Work")
        Projects.objects.create(user=self.user, name="Atlas API", context=self.context)
        self.client.login(username="finrod", password="pw")

    def test_charts_uses_the_focus_desk_shell_only(self):
        response = self.client.get(reverse("charts"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/base.html")
        self.assertContains(response, "core/css/focus_desk.css")
        self.assertNotContains(response, "core/css/style.css")

    def test_the_hooks_charts_core_js_drives_are_intact(self):
        html = self.client.get(reverse("charts")).content.decode()

        for hook in (
            'id="chart_data_link"',
            'id="chart-loading"',
            'id="chart-empty"',
            'id="canvas_container"',
            'id="chart"',
            'id="refresh-chart"',
            'id="chart_type"',
            "data-selected=",
        ):
            with self.subTest(hook=hook):
                self.assertIn(hook, html)

    def test_the_chart_picker_stays_on_the_page(self):
        """It is what the page is for; only the narrowing controls hide in the
        sheet."""
        html = self.client.get(reverse("charts")).content.decode()

        before_sheet = html.split('id="filterSheet"')[0]
        self.assertIn('id="chart_type"', before_sheet)
        self.assertIn('id="refresh-chart"', before_sheet)

    def test_the_picker_still_posts_its_type_through_apply(self):
        """Picking a type now redraws client-side without submitting, so nothing
        in the redraw path needs name="chart_type" any more. Apply still does:
        it reloads, and the type has to survive the round-trip and come back in
        data-selected."""
        html = self.client.get(
            reverse("charts"), {"chart_type": "treemap"}
        ).content.decode()

        picker = html.split('id="chart_type"')[1].split(">")[0]
        self.assertIn('name="chart_type"', picker)
        self.assertIn('data-selected="treemap"', picker)

    def test_filters_are_echoed_like_the_other_list_pages(self):
        response = self.client.get(reverse("charts"), {"context": str(self.context.id)})

        self.assertIn(
            {"label": "Context", "value": "Work"}, response.context["active_filters"]
        )
        self.assertContains(response, "filter-pill")

    def test_the_page_does_not_reload_a_second_jquery(self):
        """The shell already ships jQuery 3.6; the legacy page pulled 1.7.1 in
        after it, silently downgrading every script that followed."""
        html = self.client.get(reverse("charts")).content.decode()

        self.assertNotIn("libs/jquery/1.7.1", html)
