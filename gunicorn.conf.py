"""Gunicorn configuration for hosted deployments."""

logger_class = "AutumnWeb.gunicorn_logging.AutumnLogger"


def on_starting(server):
    """Leave one visible confirmation that this deployment config was loaded."""

    server.log.info("Autumn Gunicorn logging configuration loaded")


def post_worker_init(worker):
    """Start reminder delivery only after this worker has loaded Django."""

    from django.conf import settings

    if getattr(settings, "RUN_REMINDER_DISPATCHER", False):
        from core.services.reminder_dispatcher import start_dispatcher_thread

        start_dispatcher_thread()
