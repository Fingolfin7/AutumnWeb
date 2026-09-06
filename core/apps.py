import logging
import os
import sys

from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger(__name__)


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        import core.signals  # make sure signals are imported and therefore run

        # Opt-in in-process timer reminder dispatcher.  Starting it must never
        # break startup, so every failure here is logged and swallowed.
        try:
            if getattr(settings, "RUN_REMINDER_DISPATCHER", False):
                from core.services.reminder_dispatcher import (
                    should_start_dispatcher,
                    start_dispatcher_thread,
                )

                if should_start_dispatcher(sys.argv, os.environ, enabled=True):
                    start_dispatcher_thread()
        except Exception:
            logger.exception("Could not start the timer reminder dispatcher thread.")
