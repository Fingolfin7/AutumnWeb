from datetime import timedelta, time, datetime

from django import template

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

    return f"{days_str}{hrs_str}{min_str}{sec_str}"
