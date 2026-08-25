"""Gunicorn logging configuration for hosted deployments."""

import logging
from collections.abc import Mapping


QUIET_SUCCESS_PATHS = frozenset(
    {
        "/healthz/",
        "/timeline/fragment/",
        "/timers/active-fragment/",
    }
)


class SuccessfulPollingRequestFilter(logging.Filter):
    """Hide successful high-frequency GETs while preserving their failures."""

    def filter(self, record):
        atoms = record.args
        if not isinstance(atoms, Mapping):
            return True

        method = str(atoms.get("m", "")).upper()
        path = str(atoms.get("U", ""))
        status = str(atoms.get("s", ""))
        is_success = status.startswith(("2", "3"))

        return not (
            method == "GET"
            and path in QUIET_SUCCESS_PATHS
            and is_success
        )


def post_fork(server, worker):
    """Install the filter in each worker after Gunicorn forks it."""

    server.log.access_log.addFilter(SuccessfulPollingRequestFilter())
