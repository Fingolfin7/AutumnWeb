"""Gunicorn logger customizations used by the Render web process."""

from gunicorn.glogging import Logger

from AutumnWeb.access_log_policy import should_log_access


class AutumnLogger(Logger):
    """Avoid creating access records for successful high-frequency polling."""

    def access(self, resp, req, environ, request_time):
        if should_log_access(
            environ.get("REQUEST_METHOD", ""),
            environ.get("PATH_INFO", ""),
            getattr(resp, "status", ""),
        ):
            super().access(resp, req, environ, request_time)
