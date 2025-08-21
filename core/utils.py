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
    """"
    Parse a date or datetime string into a datetime object. Supports the following formats:
    %m-%d-%Y, %m-%d-%Y %H:%M:%S, %Y-%m-%d, %Y-%m-%d %H:%M:%S

    :param date_str: the date or datetime string to parse
    :return: a datetime object
    :raises ValueError: if the date_str is not in a recognized format

    """
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
    # Determine the correct query parameters attribute safely
    query_params = getattr(request, "query_params", None)
    if query_params is None:
        query_params = getattr(request, "GET", {})

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
        sessions = sessions.filter(start_time__gte=start)
    if end_date:
        end = timezone.make_aware(parse_date_or_datetime(end_date) + timedelta(days=1))
        sessions = sessions.filter(start_time__lte=end)


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


def build_project_json_from_sessions(sessions, autumn_compatible=False):
    """
    Build the nested export‐JSON given a flat iterable of Session instances.
    Only subprojects that actually appear in those sessions are emitted.
    """
    projects_data = {}
    # bucket sessions by project name
    sessions_by_project = defaultdict(list)
    for sess in reversed(sessions):
        sessions_by_project[sess.project.name].append(sess)

    for project_name, sess_list in sessions_by_project.items():
        # grab the project instance for metadata
        project_obj = sess_list[0].project

        # build the session history list and tally total time
        history = []
        total_proj_minutes = 0
        for s in sess_list:
            total_proj_minutes += s.duration
            history.append({
                "Date":       timezone.localtime(s.end_time).strftime("%m-%d-%Y"),
                "Start Time": timezone.localtime(s.start_time).strftime("%H:%M:%S"),
                "End Time":   timezone.localtime(s.end_time).strftime("%H:%M:%S"),
                "Sub-Projects": [sp.name for sp in s.subprojects.all()],
                "Duration":   s.duration,
                "Note":       s.note or ""
            })

        # determine project start / last dates from history
        start_date = history[0]["Date"] if history else ""
        last_date  = history[-1]["Date"] if history else ""

        # aggregate subprojects from those same sessions
        sub_sessions = defaultdict(list)
        for s in sess_list:
            for sp in s.subprojects.all():
                sub_sessions[sp.name].append((s, sp))

        subprojects_data = {}
        for sub_name, sess_and_sp in sub_sessions.items():
            # sess_and_sp is a list of (session, subproject_instance) tuples
            # sort by session end_time
            sess_and_sp.sort(key=lambda pair: pair[0].end_time)

            # total time = sum of durations of sessions in which this subproject appears
            total_sub_minutes = sum(s.duration for s, _ in sess_and_sp)

            if autumn_compatible:
                subprojects_data[sub_name] = total_sub_minutes
            else:
                # pick the first .subproject instance for description / dates
                first_s, first_sp = sess_and_sp[0]
                last_s, _         = sess_and_sp[-1]
                subprojects_data[sub_name] = {
                    "Start Date": timezone.localtime(first_s.end_time).strftime("%m-%d-%Y"),
                    "Last Updated": timezone.localtime(last_s.end_time).strftime("%m-%d-%Y"),
                    "Total Time": total_sub_minutes,
                    "Description": first_sp.description or ""
                }

        projects_data[project_name] = {
            "Start Date":  start_date,
            "Last Updated": last_date,
            "Total Time":  total_proj_minutes,
            "Status":      project_obj.status,
            "Description": project_obj.description or "",
            "Sub Projects": subprojects_data,
            "Session History": history
        }

    return projects_data


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
