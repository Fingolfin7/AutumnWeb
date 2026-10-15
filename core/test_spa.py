import json
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from core import spa
from core.models import Context

MANIFEST = {
    "src/main.tsx": {
        "file": "assets/main-abc123.js",
        "isEntry": True,
        "css": ["assets/main-def456.css"],
        "imports": ["_vendor-1.js"],
    },
    "_vendor-1.js": {"file": "assets/vendor-xyz.js"},
}


@mock.patch.object(spa, "manifest", return_value=MANIFEST)
class SpaViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("spa-user", "spa@example.com", "pw-12345!")
        Context.objects.create(user=self.user, name="Work")

    def test_anonymous_users_are_sent_to_login(self, _manifest):
        response = self.client.get("/sessions/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_renders_bundle_and_bootstrap(self, _manifest):
        self.client.force_login(self.user)
        response = self.client.get("/sessions/")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('<div id="root"></div>', html)
        self.assertIn("/static/app/assets/main-abc123.js", html)
        self.assertIn("/static/app/assets/main-def456.css", html)
        self.assertIn('rel="modulepreload" href="/static/app/assets/vendor-xyz.js"', html)
        start = html.index('id="autumn-bootstrap"')
        blob = html[html.index(">", start) + 1 : html.index("</script>", start)]
        data = json.loads(blob)
        self.assertEqual(data["user"]["username"], "spa-user")
        self.assertEqual([c["name"] for c in data["contexts"]], ["Work"])
        self.assertTrue(data["csrf_token"])

    def test_marked_as_the_offline_shell_and_not_browser_cached(self, _manifest):
        self.client.force_login(self.user)
        response = self.client.get("/sessions/")
        self.assertEqual(response["X-Autumn-Shell"], "1")
        self.assertIn("no-cache", response["Cache-Control"])
        self.assertIn("private", response["Cache-Control"])

    def test_unknown_paths_are_real_404s(self, _manifest):
        # Only the app's own pages serve it (core/urls.py points them at
        # spa); anything else is a server 404, signed in or not.
        self.assertEqual(self.client.get("/debug-session/").status_code, 404)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/no/such/page/").status_code, 404)

    def test_api_and_static_paths_are_not_swallowed(self, _manifest):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/api/v2/definitely-missing/").status_code, 404)
        missing_static = self.client.get("/static/app/assets/missing.js")
        self.assertEqual(missing_static.status_code, 404)
        self.assertNotIn(b'id="root"', missing_static.content)

    @override_settings(VITE_DEV_SERVER="http://localhost:5173")
    def test_dev_server_mode_loads_from_vite(self, _manifest):
        self.client.force_login(self.user)
        html = self.client.get("/sessions/").content.decode()
        self.assertIn('src="http://localhost:5173/src/main.tsx"', html)
        self.assertIn("http://localhost:5173/@vite/client", html)

    def test_missing_build_is_a_clear_404(self, manifest_mock):
        manifest_mock.return_value = None
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/sessions/").status_code, 404)

    def test_server_rendered_pages_still_win(self, _manifest):
        self.client.force_login(self.user)
        response = self.client.get("/export/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'id="autumn-bootstrap"', response.content)

    def test_old_reminder_pages_open_the_matching_dialog(self, _manifest):
        self.client.force_login(self.user)
        for action in ("edit", "snooze", "cancel"):
            response = self.client.get(f"/notifications/schedules/7/{action}/")
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response["Location"], f"/notifications/?{action}=7")
