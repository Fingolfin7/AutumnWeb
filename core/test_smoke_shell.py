"""Server-rendered pages sit on the new shell and only the new shell, and the
static files and service worker they rely on exist.

A blunt sweep: it will not catch a bad layout, but it catches a page that
500s, that quietly still pulls style.css, or that was missed entirely. The
React pages are covered by core/test_spa.py and the frontend tests.
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
        cls.user.profile.set_api_key("openai", "test-openai-key")
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
        # Everything else is the React app (core/test_spa.py): what is still
        # rendered by Django on the Night Ledger shell.
        return [reverse("recommendation_usage")]

    def test_every_server_rendered_page_renders_on_the_new_shell_only(self):
        for url in self.ported_urls():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200, url)
                body = response.content.decode()
                self.assertIn("core/css/focus_desk.css", body)
                self.assertNotIn("core/css/style.css", body)

    def test_every_referenced_static_file_exists(self):
        """A <script src> or <link href> pointing at a deleted file fails
        silently: the page still renders 200 and the behaviour just stops.

        Chunk 13 deleted style.css, colours.css, script.js, dynamic_timers.js,
        session_sliders.js, home_timers.js and charts.js, so this sweeps every
        local static URL the pages actually emit and checks it is on disk.
        """
        import re
        from pathlib import Path

        from django.conf import settings

        pattern = re.compile(r'(?:src|href)="(/static/[^"?]+)')
        seen = set()
        for url in self.ported_urls():
            seen.update(pattern.findall(self.client.get(url).content.decode()))

        self.assertTrue(seen, "no static references found — is the regex stale?")
        root = Path(settings.BASE_DIR)
        for ref in sorted(seen):
            with self.subTest(static=ref):
                # /static/core/js/x.js -> core/static/core/js/x.js
                relative = ref[len("/static/"):]
                app_dir = relative.split("/", 1)[0]
                self.assertTrue(
                    (root / app_dir / "static" / relative).is_file(),
                    f"{ref} is referenced but does not exist on disk",
                )

    def test_service_worker_precaches_only_files_that_exist(self):
        """cache.addAll is all-or-nothing: one 404 rejects the install and the
        service worker never activates, taking offline support with it."""
        import re
        from pathlib import Path

        from django.conf import settings

        root = Path(settings.BASE_DIR)
        source = (
            root / "core" / "static" / "core" / "pwa" / "service-worker.js"
        ).read_text(encoding="utf-8")
        block = source.split("PRECACHE_URLS = [", 1)[1].split("]", 1)[0]
        urls = re.findall(r'"(/static/[^"]+)"', block)

        self.assertTrue(urls, "precache list is empty — did the format change?")
        for ref in urls:
            with self.subTest(static=ref):
                relative = ref[len("/static/"):]
                app_dir = relative.split("/", 1)[0]
                self.assertTrue(
                    (root / app_dir / "static" / relative).is_file(),
                    f"{ref} is precached but does not exist on disk",
                )

    def test_service_worker_has_safe_timer_notification_handlers(self):
        from pathlib import Path

        source = (
            Path(__file__).parent / "static" / "core" / "pwa" / "service-worker.js"
        ).read_text(encoding="utf-8")

        self.assertIn('addEventListener("push"', source)
        self.assertIn('addEventListener("notificationclick"', source)
        self.assertIn('"autumn-" + category + "-" + identity', source)
        self.assertIn("safeNotificationTag(payload.tag, category, identity)", source)
        self.assertIn('openWindow(target)', source)
        self.assertIn('path === prefix || path.startsWith(prefix + "/")', source)
        self.assertIn('timer: ["/timers"]', source)

    def test_no_ported_page_reloads_a_second_jquery(self):
        """The shell ships jQuery 3.6; the legacy pages pulled 1.7.1 in after
        it, silently downgrading every script that followed."""
        for url in self.ported_urls():
            with self.subTest(url=url):
                body = self.client.get(url).content.decode()
                self.assertNotIn("libs/jquery/1.7.1", body)
