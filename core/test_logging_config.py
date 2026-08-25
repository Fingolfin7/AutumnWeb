import importlib.util

from django.conf import settings
from django.test import SimpleTestCase

from AutumnWeb.access_log_policy import should_log_access


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
    def test_gunicorn_uses_the_custom_logger(self):
        self.assertEqual(
            load_gunicorn_config().logger_class,
            "AutumnWeb.gunicorn_logging.AutumnLogger",
        )

    def test_successful_health_and_polling_requests_are_suppressed(self):
        for path in (
            "/healthz/",
            "/timeline/fragment/",
            "/timers/active-fragment/",
        ):
            with self.subTest(path=path):
                self.assertFalse(should_log_access("GET", path, "200 OK"))

    def test_failures_on_quiet_paths_remain_visible(self):
        self.assertTrue(should_log_access("GET", "/healthz/", "500 Internal Error"))

    def test_ordinary_successful_requests_remain_visible(self):
        self.assertTrue(should_log_access("GET", "/sessions/", "200 OK"))

    def test_non_get_requests_to_quiet_paths_remain_visible(self):
        self.assertTrue(should_log_access("POST", "/healthz/", "204 No Content"))
