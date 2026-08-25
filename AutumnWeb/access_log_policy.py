"""Pure access-log filtering policy shared by Gunicorn and unit tests."""

QUIET_SUCCESS_PATHS = frozenset(
    {
        "/healthz/",
        "/timeline/fragment/",
        "/timers/active-fragment/",
    }
)


def should_log_access(method, path, status):
    """Keep ordinary requests and all failures; drop successful polling GETs."""

    status_code = str(status).split(None, 1)[0]
    is_success = status_code.startswith(("2", "3"))

    return not (
        str(method).upper() == "GET"
        and str(path) in QUIET_SUCCESS_PATHS
        and is_success
    )
