"""Gunicorn configuration for hosted deployments."""

logger_class = "AutumnWeb.gunicorn_logging.AutumnLogger"


def on_starting(server):
    """Leave one visible confirmation that this deployment config was loaded."""

    server.log.info("Autumn Gunicorn logging configuration loaded")
