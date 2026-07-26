"""Tests for the Focus Desk sessions pages (UI_REDESIGN.md chunk 3).

The filter sheet hides the controls, so the page has to say what is narrowing
the list. If that echo is wrong, a filtered list that comes back empty is
indistinguishable from a broken one — which is exactly what these pin down.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Context, Projects, Sessions, SubProjects, Tag
from core.utils import summarise_search_filters


class SessionsPageTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="finrod", password="pw")
        self.context = Context.objects.create(user=self.user, name="Work")
        self.atlas = Projects.objects.create(
            user=self.user, name="Atlas API", context=self.context
        )
        self.autumn = Projects.objects.create(
            user=self.user, name="Autumn", context=self.context
        )
        self.tag = Tag.objects.create(user=self.user, name="deep-work")
        self.client.login(username="finrod", password="pw")

    def _session(self, project, minutes_ago=30, note=None, subs=()):
        end = timezone.now() - timedelta(minutes=minutes_ago)
        session = Sessions.objects.create(
            user=self.user,
            project=project,
            start_time=end - timedelta(minutes=30),
            end_time=end,
            note=note,
        )
        for name in subs:
            sub, _ = SubProjects.objects.get_or_create(
                user=self.user, parent_project=project, name=name
            )
            session.subprojects.add(sub)
        return session


class FilterSummaryTests(SessionsPageTestCase):
    def test_no_query_means_nothing_to_echo(self):
        response = self.client.get(reverse("sessions"))
        self.assertEqual(response.context["active_filters"], [])

    def test_text_filters_are_echoed_verbatim(self):
        response = self.client.get(
            reverse("sessions"), {"project_name": "Atlas API", "note_snippet": "stripe"}
        )
        self.assertEqual(
            response.context["active_filters"],
            [
                {"label": "Project", "value": "Atlas API"},
                {"label": "Note", "value": "stripe"},
            ],
        )

    def test_ids_are_resolved_to_names(self):
        """A pill reading "Context 3" would tell the user nothing."""
        response = self.client.get(
            reverse("sessions"),
            {"context": str(self.context.id), "tags": [str(self.tag.id)]},
        )
        self.assertIn(
            {"label": "Context", "value": "Work"}, response.context["active_filters"]
        )
        self.assertIn(
            {"label": "Tags", "value": "deep-work"}, response.context["active_filters"]
        )

    def test_another_users_ids_resolve_to_nothing(self):
        other = User.objects.create_user(
            username="curufin", email="curufin@example.com", password="pw"
        )
        theirs = Context.objects.create(user=other, name="Forge")

        summary = summarise_search_filters(
            self._request_with({"context": str(theirs.id)}), self.user
        )

        self.assertEqual(summary, [])

    def test_junk_ids_do_not_raise(self):
        """Query strings are user input; a non-numeric id must not 500."""
        response = self.client.get(reverse("sessions"), {"tags": ["not-a-number"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_filters"], [])

    def _request_with(self, params):
        from django.test import RequestFactory

        return RequestFactory().get(reverse("sessions"), params)


class ResultCountTests(SessionsPageTestCase):
    def test_count_is_the_whole_result_set_not_the_page(self):
        """paginate_by is 7; the count must not silently mean "on this page"."""
        for index in range(9):
            self._session(self.atlas, minutes_ago=index * 60)

        response = self.client.get(reverse("sessions"))

        self.assertEqual(response.context["result_count"], 9)
        self.assertEqual(len(response.context["object_list"]), 7)

    def test_count_reflects_the_filter(self):
        self._session(self.atlas, note="stripe webhook backfill")
        self._session(self.autumn, note="dark mode pass")

        response = self.client.get(reverse("sessions"), {"note_snippet": "stripe"})

        self.assertEqual(response.context["result_count"], 1)


class SessionsShellTests(SessionsPageTestCase):
    def test_all_three_pages_use_the_focus_desk_shell_only(self):
        session = self._session(self.atlas, subs=["auth"])
        pages = [
            reverse("sessions"),
            reverse("update_session", args=[session.id]),
            reverse("delete_session", args=[session.id]),
        ]

        for url in pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "core/base_fd.html")
                self.assertContains(response, "core/css/focus_desk.css")
                self.assertNotContains(response, "core/css/style.css")

    def test_list_renders_rows_and_the_filter_launcher(self):
        self._session(self.atlas, note="a note", subs=["auth"])

        response = self.client.get(reverse("sessions"))

        self.assertContains(response, "session-list")
        self.assertContains(response, 'data-sheet-open="filterSheet"')
        self.assertContains(response, "Atlas API")

    def test_the_edit_page_keeps_list_subs_outside_the_replaced_container(self):
        """timer_search_projects.js wipes #subproject_options on every project
        change; the ajax url template has to survive that."""
        session = self._session(self.atlas, subs=["auth"])

        html = self.client.get(reverse("update_session", args=[session.id])).content.decode()

        before_container = html.split('id="subproject_options"')[0]
        self.assertIn('id="list_subs"', before_container)

    def test_the_empty_list_distinguishes_no_data_from_no_matches(self):
        no_data = self.client.get(reverse("sessions"))
        self.assertContains(no_data, "No sessions yet")

        self._session(self.atlas)
        no_matches = self.client.get(reverse("sessions"), {"note_snippet": "zzz"})
        self.assertContains(no_matches, "No sessions match these filters")
