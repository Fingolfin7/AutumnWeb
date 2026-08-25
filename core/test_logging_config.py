import importlib.util
import logging

from django.conf import settings
from django.test import SimpleTestCase


def load_gunicorn_config():
    config_path = settings.BASE_DIR / "gunicorn.conf.py"
    spec = importlib.util.spec_from_file_location("autumn_gunicorn_config", config_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DjangoLoggingConfigurationTests(SimpleTestCase):
    def test_application_loggers_are_visible_on_the_console(self):
        for logger_name in (
            "AutumnWeb",
            "core",
            "users",
            "llm_insights",
            "main",
            "signals",
            "models",
            "django",
        ):
            with self.subTest(logger=logger_name):
                self.assertIn("console", settings.LOGGING["loggers"][logger_name]["handlers"])

    def test_console_format_contains_searchable_fields(self):
        log_format = settings.LOGGING["formatters"]["structured"]["format"]

        self.assertIn("level=%(levelname)s", log_format)
        self.assertIn("logger=%(name)s", log_format)


class GunicornAccessLogFilterTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.log_filter = load_gunicorn_config().SuccessfulPollingRequestFilter()

    def make_record(self, *, method="GET", path="/healthz/", status="200"):
        record = logging.LogRecord(
            name="gunicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="request",
            args=(),
            exc_info=None,
        )
        record.args = {"m": method, "U": path, "s": status}
        return record

    def test_successful_health_and_polling_requests_are_suppressed(self):
        for path in (
            "/healthz/",
            "/timeline/fragment/",
            "/timers/active-fragment/",
        ):
            with self.subTest(path=path):
                self.assertFalse(self.log_filter.filter(self.make_record(path=path)))

    def test_failures_on_quiet_paths_remain_visible(self):
        self.assertTrue(
            self.log_filter.filter(self.make_record(path="/healthz/", status="500"))
        )

    def test_ordinary_successful_requests_remain_visible(self):
        self.assertTrue(
            self.log_filter.filter(self.make_record(path="/sessions/", status="200"))
        )

    def test_non_get_requests_to_quiet_paths_remain_visible(self):
        self.assertTrue(
            self.log_filter.filter(
                self.make_record(method="POST", path="/healthz/", status="204")
            )
        )

    def test_unstructured_records_remain_visible(self):
        record = self.make_record()
        record.args = ()

        self.assertTrue(self.log_filter.filter(record))
