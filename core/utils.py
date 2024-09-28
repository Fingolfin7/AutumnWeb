from django.utils import timezone
from collections import defaultdict
from django.db.models import QuerySet
from datetime import datetime, timedelta
from core.models import Sessions, Projects, SubProjects


def parse_date_or_datetime(date_str):
    date_formats = ['%m-%d-%Y', '%m-%d-%Y %H:%M:%S', '%Y-%m-%d', '%Y-%m-%d %H:%M:%S']
    for fmt in date_formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Date string '{date_str}' is not in a recognized format")


def in_window(data: QuerySet, start: datetime | str = None, end: datetime | str = None) -> list:
    """
    Return a list of items in the data set that fall within the given window. Use this only when you need to
    filter items by the get_start and get_end properties of the items since those cant be used in a filter
    query. Otherwise, use the filter method of the QuerySet since it's more efficient.

    :param data: a queryset of items
    :param start: the start of the window (%m-%d-%Y) or (%m-%d-%Y %H:%M:%S)
    :param end: the end of the window (%m-%d-%Y) or (%m-%d-%Y %H:%M:%S)

    :return: a list of items that fall within the window
    """

    if isinstance(start, str):
        start = parse_date_or_datetime(start)
    if isinstance(end, str):
        end = parse_date_or_datetime(end)

    end = end + timedelta(days=1) if end else None  # add a day to the end date to include all sessions on that day

    # can't use the filter property of a QuerySet because it doesn't support the get_start and get_end properties
    try:
        if end:
            return [item for item in data if item.get_start >= start and item.get_end <= end]
        else:
            return [item for item in data if item.get_start >= start]
    except TypeError:
        start = timezone.make_aware(start)
        if end:
            end = timezone.make_aware(end)
            return [item for item in data if item.get_start >= start and item.get_end <= end]
        else:
            return [item for item in data if item.get_start >= start]


def filter_by_projects(data: QuerySet[Projects | SubProjects | Sessions], name: str = None,
                       names: list[str] = None) -> QuerySet:
    """
    filter a queryset of data and return a list of items that match the given project name or names
    :param data: a queryset of data
    :param name: if you need to filter for 1 name
    :param names: if you need to filter for multiple names
    :return: list of items that match the given name or names
    """
    if len(data) == 0:
        return data

    item = data[0]  # get the first item in the queryset to determine the type of data
    if name:
        if isinstance(item, Projects):
            return data.filter(name__icontains=name)
        elif isinstance(item, SubProjects):
            return data.filter(parent_project__name__icontains=name)
        elif isinstance(item, Sessions):
            return data.filter(project__name__icontains=name)
    elif names:
        if isinstance(item, Projects):
            return data.filter(name__in=names)
        elif isinstance(item, SubProjects):
            return data.filter(parent_project__name__in=names)
        elif isinstance(item, Sessions):
            return data.filter(project__name__in=names)
    else:
        return data


def filter_sessions_by_params(request, sessions: QuerySet[Sessions]) -> QuerySet:
    # Determine the correct query parameters attribute
    query_params = getattr(request, 'query_params', request.GET)

    project_name = query_params.get('project_name')
    subproject_name = query_params.get('subproject')
    project_names = query_params.get('projects')
    if project_names:
        project_names = project_names.split(',')
    subproject_names = query_params.get('subprojects')
    if subproject_names:
        subproject_names = subproject_names.split(',')

    if project_name:
        sessions = filter_by_projects(sessions, name=project_name)
        if subproject_name:
            sessions = sessions.filter(subprojects__name__icontains=subproject_name)
    elif project_names:
        sessions = filter_by_projects(sessions, names=project_names)
        if subproject_names:
            sessions = sessions.filter(subprojects__name__in=subproject_names)

    if 'note_snippet' in query_params:
        sessions = sessions.filter(note__icontains=query_params['note_snippet'])

    start_date = query_params.get('start_date')
    end_date = query_params.get('end_date')

    if start_date:
        start = timezone.make_aware(parse_date_or_datetime(start_date))
        if end_date:
            end = timezone.make_aware(parse_date_or_datetime(end_date) + timedelta(days=1))
            sessions = sessions.filter(start_time__range=[start, end])
        else:
            sessions = sessions.filter(start_time__gte=start)

    # print(len(sessions))
    return sessions


def tally_project_durations(sessions) -> list[dict]:
    """
    Tally the total duration of each project in the given list of sessions
    :param sessions: iterable of sessions
    :return: list of tuples containing the project name and its total duration
    """

    project_durations = defaultdict(timedelta)  # avoids the need to check if a key exists before updating it

    for session in sessions:
        project_name = session.project.name
        duration = session.end_time - session.start_time
        project_durations[project_name] += duration


    return [{'name': name, 'total_time': total.total_seconds()/60} for name, total in project_durations.items()]