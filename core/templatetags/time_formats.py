from datetime import timedelta, time, datetime

from django import template
from django.utils import timezone

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
    plural_form = lambda counter: 's'[:counter ^ 1]

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
    Converts timedelta objects into formatted time strings showing durations. E.g. 1 day 2 hours 28 minutes 56 seconds
    :param td: timedelta objects
    :return: string formatted to days, hours, minutes and seconds.
    """
    if isinstance(td, (float, int)):
        td = timedelta(minutes=td)

    d_total = str(td).split(".")[0]
    d_total = datetime.strptime(d_total, "%H:%M:%S")

    if d_total.hour > 0:
        return d_total.strftime("%Hh %Mm")
    else:
        return d_total.strftime("%Mm %Ss")


@register.filter
def date_formatter(date: datetime | str):
    """
    Converts datetime objects into formatted date strings. E.g. 12 June 2021
    :param date: datetime objects
    :return: string formatted to day month year.
    """
    if isinstance(date, str):
        try:
            date = datetime.strptime(date, "%m-%d-%Y")
        except ValueError:
            date = datetime.strptime(date, "%Y-%m-%d")

    if timezone.is_naive(date):
        date = timezone.make_aware(date)
    else:
        date = date.astimezone(timezone.get_default_timezone())
    return date.strftime("%d %B %Y")


@register.filter
def time_formatter(date: datetime):
    """
    Converts datetime objects into formatted time strings. E.g. 12:30
    :param date: datetime objects
    :return: string formatted to hour and minutes.
    """
    if timezone.is_naive(date):
        date = timezone.make_aware(date)
    else:
        date = date.astimezone(timezone.get_default_timezone())
    return date.strftime("%H:%M:%S")


@register.filter
def day_date_formatter(date: datetime| str):
    """
    Converts datetime objects into formatted date strings. E.g. Saturday 12 June 2021
    :param date: datetime objects
    :return: string formatted to day month year.
    """
    if isinstance(date, str):

        try:
            date = datetime.strptime(date, "%m-%d-%Y")
        except ValueError:
            date = datetime.strptime(date, "%Y-%m-%d")

    if timezone.is_naive(date):
        date = timezone.make_aware(date)
    else:
        date = date.astimezone(timezone.get_default_timezone())
    return date.strftime("%A %d %b %Y")
