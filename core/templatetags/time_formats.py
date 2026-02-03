from datetime import timedelta, datetime
from datetime import timezone as dt_tz
from django import template
from django.utils import timezone
from django.utils.html import format_html

register = template.Library()


@register.filter
def min_formatter(td: timedelta | float | int):
    """
    Converts timedelta objects into formatted time strings showing durations. E.g. 1 day 2 hours 28 minutes 56 seconds
    :param td: timedelta objects
    :return: string formatted to days, hours, minutes and seconds.
    """
    if isinstance(td, (float, int)):
        td = timedelta(minutes=td)

    days = td.days
    hrs, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    plural_form = lambda counter: "s"[: counter ^ 1]

    if days > 0:
        days_str = f"{days} day{plural_form(days)} "
    else:
        days_str = ""

    if hrs > 0:
        hrs_str = f"{hrs} hour{plural_form(hrs)} "
    else:
        hrs_str = ""

    if minutes > 0:
        min_str = f"{minutes} minute{plural_form(minutes)} "
    else:
        min_str = ""

    if seconds > 0:
        sec_str = f"{seconds} second{plural_form(seconds)} "
    else:
        sec_str = ""

    build_string = f"{days_str}{hrs_str}{min_str}{sec_str}"
    return build_string if build_string else "0 seconds"


@register.filter
def duration_formatter(td: timedelta | float | int):
    """
    Converts timedelta objects into formatted time strings like "1d 2h 30m" or "45m 30s"
    """
    if isinstance(td, (float, int)):
        td = timedelta(minutes=td)

    days = td.days
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if days > 0:
        return f"{days:02d}d {hours:02d}h {minutes:02d}m"
    if hours > 0:
        return f"{hours:02d}h {minutes:02d}m"
    return f"{minutes:02d}m {seconds:02d}s"


@register.filter
def date_formatter(date: datetime | str):
    """
    Converts datetime objects into formatted date strings. E.g. 12 June 2021
    :param date: datetime objects
    :return: string formatted to day month year.
    """
    date = make_timezone_datetime(date)
    if not date or isinstance(date, str):
        return ""
    return date.strftime("%d %B %Y")


@register.filter
def time_formatter(date: datetime):
    """
    Converts datetime objects into formatted time strings. E.g. 12:30
    Outputs both UTC ISO time as data attribute and server time as fallback
    :param date: datetime objects
    :return: HTML span with UTC time data attribute
    """
    if not date:
        return ""
    if timezone.is_naive(date):
        date = timezone.make_aware(date)
    utc_time = date.astimezone(dt_tz.utc).isoformat()
    server_time = date.astimezone(timezone.get_default_timezone()).strftime("%H:%M:%S")
    return format_html('<span data-utc-time="{}">{}</span>', utc_time, server_time)


@register.filter
def utc_time_formatter(date: datetime):
    """
    Converts datetime objects into formatted UTC ISO time strings.
    :param date: datetime objects
    :return: string formatted to UTC time.
    """
    if not date:
        return ""
    if timezone.is_naive(date):
        date = timezone.make_aware(date)
    return date.astimezone(dt_tz.utc).isoformat()


@register.filter
def day_date_formatter(date: datetime | str):
    """
    Converts datetime objects into formatted date strings. E.g. Saturday 12 June 2021
    :param date: datetime objects
    :return: string formatted to day month year.
    """
    date = make_timezone_datetime(date)
    if not date or isinstance(date, str):
        return ""
    return date.strftime("%A %d %b %Y")


@register.filter
def project_status_counts_formatter(counts: dict | None) -> str:
    """Format a project status counts dict into a compact parenthesized string.

    Expected keys: active, paused, complete, archived.
    Outputs nothing if all counts are missing/zero.

    Example: "(2 active, 1 paused, 0 complete, 0 archived)" -> "(2 active, 1 paused)".
    """
    if not counts:
        return ""

    parts: list[str] = []
    for key, label in (
        ("active", "active"),
        ("paused", "paused"),
        ("complete", "complete"),
        ("archived", "archived"),
    ):
        try:
            val = int(counts.get(key) or 0)
        except (TypeError, ValueError):
            val = 0
        if val:
            parts.append(f"{val} {label}")

    if not parts:
        return ""

    return f"({', '.join(parts)})"


def make_timezone_datetime(date):
    if not date:
        return date
    if isinstance(date, str):
        try:
            date = datetime.strptime(date, "%m-%d-%Y")
        except ValueError:
            date = datetime.strptime(date, "%Y-%m-%d")

    if not isinstance(date, datetime):
        return date

    if timezone.is_naive(date):
        date = timezone.make_aware(date)
    else:
        date = date.astimezone(timezone.get_default_timezone())
    return date


@register.filter
def get_item(dictionary, key):
    """
    Access dictionary item by key in templates.
    Usage: {{ mydict|get_item:key }}
    """
    if dictionary is None:
        return None
    return dictionary.get(key)
