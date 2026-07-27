"""Every ported page must render on the new shell and only the new shell.

A blunt sweep: it will not catch a bad layout, but it catches a page that
500s, that quietly still pulls style.css, or that was missed entirely.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Commitment, Context, Projects, Sessions, SubProjects, Tag


class PortedPagesSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="smoke", email="smoke@example.com", password="pw"
        )
        cls.user.profile.ai_features_enabled = True  # so Insights renders
        cls.user.profile.save()
        cls.context = Context.objects.create(user=cls.user, name="Work")
        cls.tag = Tag.objects.create(user=cls.user, name="deep")
        cls.project = Projects.objects.create(
            user=cls.user, name="Atlas API", context=cls.context
        )
        cls.project.tags.add(cls.tag)
        cls.sub = SubProjects.objects.create(
            user=cls.user, parent_project=cls.project, name="auth"
        )
        end = timezone.now() - timedelta(hours=1)
        cls.session = Sessions.objects.create(
            user=cls.user, project=cls.project,
            start_time=end - timedelta(minutes=45), end_time=end, note="a note",
        )
        cls.session.subprojects.add(cls.sub)
        cls.timer = Sessions.objects.create(
            user=cls.user, project=cls.project,
            start_time=timezone.now() - timedelta(minutes=5),
        )
        cls.commitment = Commitment.objects.create(
            user=cls.user, project=cls.project, commitment_type="time",
            period="weekly", target=300,
        )

    def setUp(self):
        self.client.login(username="smoke", password="pw")

    def ported_urls(self):
        return [
            reverse("home"),
            reverse("sessions"),
            reverse("update_session", args=[self.session.id]),
            reverse("delete_session", args=[self.session.id]),
            reverse("projects"),
            reverse("create_project"),
            reverse("update_project", args=[self.project.id]),
            reverse("delete_project", args=[self.project.id]),
            reverse("merge_projects"),
            reverse("create_subproject", args=[self.project.id]),
            reverse("update_subproject", args=[self.sub.id]),
            reverse("delete_subproject", args=[self.sub.id]),
            reverse("merge_subprojects", args=[self.project.id]),
            reverse("timers"),
            reverse("start_timer"),
            reverse("stop_timer", args=[self.timer.id]),
            reverse("remove_timer", args=[self.timer.id]),
            reverse("delete_commitment", args=[self.commitment.id]),
            reverse("contexts"),
            reverse("update_context", args=[self.context.id]),
            reverse("delete_context", args=[self.context.id]),
            reverse("tags"),
            reverse("update_tag", args=[self.tag.id]),
            reverse("delete_tag", args=[self.tag.id]),
            reverse("charts"),
            reverse("insights"),
            reverse("import"),
            reverse("export"),
            reverse("profile"),
        ]

    def test_fragments_render_without_a_shell(self):
        """Fragments are swapped into a live page, so they must NOT carry one."""
        for url in (reverse("timeline_fragment"), reverse("active_timers_fragment")):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                body = response.content.decode()
                self.assertNotIn("<html", body)
                self.assertNotIn("focus_desk.css", body)

    def test_every_ported_page_renders_on_the_new_shell_only(self):
        for url in self.ported_urls():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200, url)
                body = response.content.decode()
                self.assertIn("core/css/focus_desk.css", body)
                self.assertNotIn("core/css/style.css", body)

    def test_no_ported_page_reloads_a_second_jquery(self):
        """The shell ships jQuery 3.6; the legacy pages pulled 1.7.1 in after
        it, silently downgrading every script that followed."""
        for url in self.ported_urls():
            with self.subTest(url=url):
                body = self.client.get(url).content.decode()
                self.assertNotIn("libs/jquery/1.7.1", body)
