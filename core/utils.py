import json
import zlib
import base64
from django.utils import timezone
from collections import defaultdict
from django.db.models import QuerySet
from django.db.models import Min, Max
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


def date_range(start_date: datetime|str, end_date: datetime|str) -> list[datetime]:
    """
    Generate a range of dates between the start and end dates (inclusive)
    :param start_date: string or datetime object representing the start date. format: %m-%d-%Y or %m-%d-%Y %H:%M:%S
    :param end_date: string or datetime object representing the end date. format: %m-%d-%Y or %m-%d-%Y %H:%M:%S
    :return: list of datetime objects representing the range of dates
    """
    if isinstance(start_date, str):
        start_date = parse_date_or_datetime(start_date)
    if isinstance(end_date, str):
        end_date = parse_date_or_datetime(end_date)

    if end_date < start_date:
        raise ValueError("End date must be later than start date")

    return [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]


def in_window(data: QuerySet|list, start: datetime | str = None, end: datetime | str = None) -> list:
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


def tally_sessions(sessions) -> float:
    """
    Tally the total duration of all sessions in the given list. The duration is returned in minutes.
    :param sessions: iterable of sessions
    :return: total duration of all sessions
    """
    if not sessions:
        return 0.0

    total = timedelta()
    for session in sessions:
        total += session.end_time - session.start_time
    return total.total_seconds() / 60


def session_exists(user, project, start_time, end_time, subproject_names, time_tolerance=timedelta(minutes=2)) -> bool:
    """
    Check if a session already exists in the database based on start and end time (with tolerance),
    subprojects, and session notes.

    :param user: User instance the session belongs to
    :param project: Project instance the session belongs to
    :param start_time: Start time of the session
    :param end_time: End time of the session
    :param subproject_names: List of subproject names for the session
    :param time_tolerance: Allowed time difference between existing session and new session
    :return: True if a matching session exists, False otherwise
    """
    # Ensure subproject names are case-insensitive during comparison
    subproject_names_lower = {name.lower() for name in subproject_names}

    # If end_time is earlier than start_time, adjust start_time (the days probably switched over at midnight)
    if end_time < start_time:
        start_time -= timedelta(days=1)

    matching_sessions = Sessions.objects.filter(
        user=user,
        project=project,
        start_time__range=(start_time - time_tolerance, start_time + time_tolerance),
        end_time__range=(end_time - time_tolerance, end_time + time_tolerance)
        # note=note # commented out to allow for note differences (e.g. typos and edits might occur)
    )

    for session in matching_sessions:
        session_subproject_names = {name.lower() for name in session.subprojects.values_list('name', flat=True)}
        if subproject_names_lower == session_subproject_names:
            return True

    return False


def sessions_get_earliest_latest(sessions) -> tuple[datetime, datetime]:
    """
    Get the earliest start time and latest end time from a queryset of sessions.

    :param sessions: Queryset of session instances
    :return: Tuple of earliest start time and latest end time
    """
    aggregated_times = sessions.aggregate(earliest_start=Min('start_time'), latest_end=Max('end_time'))
    return aggregated_times['earliest_start'], aggregated_times['latest_end']


def json_compress(j):
    ZIPJSON_KEY = 'base64(zip(o))'
    j = {
        ZIPJSON_KEY: base64.b64encode(
            zlib.compress(
                json.dumps(j).encode('utf-8')
            )
        ).decode('ascii')
    }

    return j


def json_decompress(content: dict | str | bytes) -> dict:
    ZIPJSON_KEY = 'base64(zip(o))'

    # convert binary content to string
    if isinstance(content, bytes):
        content = content.decode('utf-8')

    if isinstance(content, str):
        try:
            content = json.loads(content)
        except Exception:
            raise RuntimeError("Could not interpret the contents")

    try:
        assert (content[ZIPJSON_KEY])
        assert (set(content.keys()) == {ZIPJSON_KEY})
    except Exception:
        return content

    try:
        content = zlib.decompress(base64.b64decode(content[ZIPJSON_KEY]))
    except RuntimeError:
        raise RuntimeError("Could not decode/unzip the contents")

    try:
        content = json.loads(content)
    except RuntimeError:
        raise RuntimeError("Could interpret the unzipped contents")

    return content
