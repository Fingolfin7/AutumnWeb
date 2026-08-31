from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class FrontendRequestResilienceTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.javascript_dir = (
            Path(settings.BASE_DIR) / "core" / "static" / "core" / "js"
        )

    def _source(self, filename):
        return (self.javascript_dir / filename).read_text(encoding="utf-8")

    def test_fragment_pollers_reject_login_redirects(self):
        for filename in ("timer_poll.js", "dashboard_desk.js"):
            with self.subTest(filename=filename):
                source = self._source(filename)
                self.assertIn("response.redirected", source)
                self.assertIn("window.location.reload()", source)

    def test_mutating_requests_do_not_report_redirects_as_success(self):
        for filename in ("timer_notes.js", "timer_reminders.js"):
            with self.subTest(filename=filename):
                source = self._source(filename)
                self.assertIn("response.redirected", source)
                self.assertIn("response.json()", source)

    def test_project_search_discards_stale_ajax_responses(self):
        source = self._source("timer_search_projects.js")

        self.assertIn("autocompleteGeneration", source)
        self.assertIn("subprojectGeneration", source)
        self.assertGreaterEqual(source.count("generation !=="), 4)
