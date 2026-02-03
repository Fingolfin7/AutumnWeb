import json
import zlib
import base64
from django.utils import timezone
from collections import defaultdict
from django.db.models import QuerySet
from django.db.models import Min, Max, Sum, Count
from datetime import datetime, timedelta
from django.http import HttpRequest
from dateutil.relativedelta import relativedelta
from core.models import Sessions, Projects, SubProjects, Context, Tag


ACTIVE_CONTEXT_SESSION_KEY = "active_context_id"


def parse_date_or_datetime(date_str):
    """ "
    Parse a date or datetime string into a datetime object. Supports the following formats:
    %m-%d-%Y, %m-%d-%Y %H:%M:%S, %Y-%m-%d, %Y-%m-%d %H:%M:%S

    :param date_str: the date or datetime string to parse
    :return: a datetime object
    :raises ValueError: if the date_str is not in a recognized format

    """
    date_formats = ["%m-%d-%Y", "%m-%d-%Y %H:%M:%S", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"]
    for fmt in date_formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Date string '{date_str}' is not in a recognized format")


def in_window(
    data: QuerySet, start: datetime | str = None, end: datetime | str = None
) -> list:
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

    end = (
        end + timedelta(days=1) if end else None
    )  # add a day to the end date to include all sessions on that day

    # can't use the filter property of a QuerySet because it doesn't support the get_start and get_end properties
    try:
        if end:
            return [
                item for item in data if item.get_start >= start and item.get_end <= end
            ]
        else:
            return [item for item in data if item.get_start >= start]
    except TypeError:
        start = timezone.make_aware(start)
        if end:
            end = timezone.make_aware(end)
            return [
                item for item in data if item.get_start >= start and item.get_end <= end
            ]
        else:
            return [item for item in data if item.get_start >= start]


def filter_by_projects(
    data: QuerySet[Projects | SubProjects | Sessions],
    name: str = None,
    names: list[str] = None,
) -> QuerySet:
    """
    filter a queryset of data and return a list of items that match the given project name or names
    :param data: a queryset of data
    :param name: if you need to filter for 1 name
    :param names: if you need to filter for multiple names
    :return: list of items that match the given name or names
    """
    if not data.exists():
        return data

    item = (
        data.first()
    )  # get the first item in the queryset to determine the type of data
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


def get_active_context(
    request: HttpRequest, override_context_id: str | None = None
) -> tuple[Context | None, str]:
    """
    Resolve the active context for this request.

    Returns (context_or_none, mode) where mode is 'all' or 'single'.
    If override_context_id is provided (e.g. from an explicit query param),
    it takes precedence over the session-stored value.

    override_context_id may be either:
      - a numeric context id
      - a context name (case-insensitive)
      - 'all'
    """
    context_id = override_context_id

    if context_id is None:
        # Fall back to session
        context_id = request.session.get(ACTIVE_CONTEXT_SESSION_KEY)

    if not context_id or str(context_id).lower() == "all":
        return None, "all"

    # Try ID first, then name.
    try:
        context = Context.objects.get(id=int(context_id), user=request.user)
        return context, "single"
    except (Context.DoesNotExist, ValueError, TypeError):
        pass

    try:
        context = Context.objects.get(
            name__iexact=str(context_id).strip(), user=request.user
        )
        return context, "single"
    except (Context.DoesNotExist, ValueError, TypeError):
        # Invalid/missing context  treat as All
        return None, "all"


def set_active_context(request: HttpRequest, context_id: str | None) -> None:
    """
    Persist the active context selection into the session.
    Use 'all' or None to represent the All Contexts state.
    """
    if not context_id or str(context_id).lower() == "all":
        request.session[ACTIVE_CONTEXT_SESSION_KEY] = "all"
    else:
        request.session[ACTIVE_CONTEXT_SESSION_KEY] = str(context_id)


def filter_by_active_context(
    data: QuerySet[Projects | SubProjects | Sessions],
    request: HttpRequest,
    override_context_id: str | None = None,
) -> QuerySet:
    """
    Apply the active context filter to the given queryset.

    If the resolved mode is 'all', the queryset is returned unchanged.
    Otherwise, it is filtered so that only rows belonging to the active
    Context are included.
    """
    context, mode = get_active_context(request, override_context_id=override_context_id)

    if mode == "all" or context is None or not data.exists():
        return data

    item = data.first()

    if isinstance(item, Projects):
        return data.filter(context=context)
    if isinstance(item, SubProjects):
        return data.filter(parent_project__context=context)
    if isinstance(item, Sessions):
        return data.filter(project__context=context)

    return data


def filter_sessions_by_params(
    request, sessions: QuerySet[Sessions], params_override=None
) -> QuerySet:
    # Determine the correct query parameters attribute safely
    # If params_override is provided, use it. Otherwise fall back to request.GET
    params = params_override if params_override is not None else request.GET

    project_name = params.get("project_name")
    start_date = params.get("start_date")
    end_date = params.get("end_date")
    note_snippet = params.get("note_snippet")
    tags = params.getlist("tags")

    if project_name:
        sessions = sessions.filter(project__name__icontains=project_name)

    if start_date:
        try:
            start_dt = parse_date_or_datetime(start_date)
            sessions = sessions.filter(end_time__gte=timezone.make_aware(start_dt))
        except (ValueError, TypeError):
            pass

    if end_date:
        try:
            end_dt = parse_date_or_datetime(end_date)
            # Add one day to include all sessions on that day
            end_dt += timedelta(days=1)
            sessions = sessions.filter(end_time__lt=timezone.make_aware(end_dt))
        except (ValueError, TypeError):
            pass

    if note_snippet:
        sessions = sessions.filter(note__icontains=note_snippet)

    if tags:
        sessions = sessions.filter(project__tags__id__in=tags).distinct()

    return sessions


def group_sessions_by_date(sessions):
    """
    Group a list or queryset of sessions by their end_time date.
    Returns an OrderedDict with date strings as keys and dicts with 'sessions' and 'total_duration'.
    """
    from collections import OrderedDict

    grouped = OrderedDict()

    # Sort sessions by end_time descending to ensure grouping order
    sorted_sessions = sorted(
        sessions, key=lambda s: s.end_time or timezone.now(), reverse=True
    )

    for session in sorted_sessions:
        if not session.end_time:
            continue

        # Get local date string
        local_end_time = timezone.localtime(session.end_time)
        session_date = local_end_time.strftime("%m-%d-%Y")

        if session_date not in grouped:
            grouped[session_date] = {"sessions": [], "total_duration": 0}

        grouped[session_date]["sessions"].append(session)
        grouped[session_date]["total_duration"] += session.duration or 0

    return grouped


def tally_project_durations(sessions) -> list[dict]:
    """
    Tally the total duration of each project in the given list of sessions
    :param sessions: iterable of sessions
    :return: list of tuples containing the project name and its total duration
    """

    project_durations = defaultdict(
        timedelta
    )  # avoids the need to check if a key exists before updating it

    for session in sessions:
        project_name = session.project.name
        duration = session.end_time - session.start_time
        project_durations[project_name] += duration

    return [
        {"name": name, "total_time": total.total_seconds() / 60}
        for name, total in project_durations.items()
    ]


def session_exists(
    user,
    project,
    start_time,
    end_time,
    subproject_names,
    time_tolerance=timedelta(minutes=2),
) -> bool:
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
        end_time__range=(end_time - time_tolerance, end_time + time_tolerance),
        # note=note # commented out to allow for note differences (e.g. typos and edits might occur)
    )

    for session in matching_sessions:
        session_subproject_names = {
            name.lower() for name in session.subprojects.values_list("name", flat=True)
        }
        if subproject_names_lower == session_subproject_names:
            return True

    return False


def sessions_get_earliest_latest(sessions) -> tuple[datetime, datetime]:
    """
    Get the earliest start time and latest end time from a queryset of sessions.

    :param sessions: Queryset of session instances
    :return: Tuple of earliest start time and latest end time
    """
    aggregated_times = sessions.aggregate(
        earliest_start=Min("start_time"), latest_end=Max("end_time")
    )
    return aggregated_times["earliest_start"], aggregated_times["latest_end"]


def _normalize_tags_payload(tags_payload) -> list[dict]:
    """
    Accepts:
      - ["tag1", "tag2"]
      - [{"name": "tag1", "color": "#fff"}, ...]
      - "tag1, tag2"
    Returns a list of dicts: [{"name": "...", "color": ...}, ...]
    """
    if not tags_payload:
        return []

    if isinstance(tags_payload, str):
        parts = [p.strip() for p in tags_payload.split(",")]
        return [{"name": p, "color": None} for p in parts if p]

    if isinstance(tags_payload, list):
        normalized = []
        for item in tags_payload:
            if isinstance(item, str):
                name = item.strip()
                if name:
                    normalized.append({"name": name, "color": None})
            elif isinstance(item, dict):
                name = str(item.get("name", "")).strip()
                if name:
                    normalized.append({"name": name, "color": item.get("color")})
        return normalized

    return []


def apply_context_and_tags_to_project(
    *,
    user,
    project: Projects,
    project_data: dict,
    merge: bool,
) -> None:
    """
    Apply Context + Tags to a project (backwards compatible).

    merge=False: treat incoming data as authoritative (set/clear)
    merge=True:  do not overwrite existing context; union tags
    """
    # Context (only act if the key exists in the import)
    if "Context" in project_data:
        context_name = (project_data.get("Context") or "").strip()

        if context_name:
            ctx, _ = Context.objects.get_or_create(
                user=user,
                name=context_name,
            )
        else:
            ctx = None

        if not merge:
            project.context = ctx
            project.save(update_fields=["context"])
        else:
            # merge behavior: only set if project currently has no context
            if project.context_id is None and ctx is not None:
                project.context = ctx
                project.save(update_fields=["context"])

    # Tags (only act if the key exists in the import)
    if "Tags" in project_data:
        tags_payload = project_data.get("Tags")
        normalized = _normalize_tags_payload(tags_payload)

        tag_objs = []
        for t in normalized:
            tag, created = Tag.objects.get_or_create(
                user=user,
                name=t["name"],
                defaults={"color": t.get("color")},
            )
            # If you want to update color on existing tags, do it here.
            tag_objs.append(tag)

        if not merge:
            project.tags.set(tag_objs)  # authoritative (can clear)
        else:
            project.tags.add(*tag_objs)  # union


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
            history.append(
                {
                    "Date": timezone.localtime(s.end_time).strftime("%m-%d-%Y"),
                    "Start Time": timezone.localtime(s.start_time).strftime("%H:%M:%S"),
                    "End Time": timezone.localtime(s.end_time).strftime("%H:%M:%S"),
                    "Sub-Projects": [sp.name for sp in s.subprojects.all()],
                    "Duration": s.duration,
                    "Note": s.note or "",
                }
            )

        # determine project start / last dates from history
        start_date = history[0]["Date"] if history else ""
        last_date = history[-1]["Date"] if history else ""

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
                last_s, _ = sess_and_sp[-1]
                subprojects_data[sub_name] = {
                    "Start Date": timezone.localtime(first_s.end_time).strftime(
                        "%m-%d-%Y"
                    ),
                    "Last Updated": timezone.localtime(last_s.end_time).strftime(
                        "%m-%d-%Y"
                    ),
                    "Total Time": total_sub_minutes,
                    "Description": first_sp.description or "",
                }

        projects_data[project_name] = {
            "Start Date": start_date,
            "Last Updated": last_date,
            "Total Time": total_proj_minutes,
            "Status": project_obj.status,
            "Description": project_obj.description or "",
            # Keep CLI compatibility: only emit these when not autumn_compatible
            **(
                {}
                if autumn_compatible
                else {
                    "Context": project_obj.context.name if project_obj.context else "",
                    "Tags": [t.name for t in project_obj.tags.all()],
                }
            ),
            "Sub Projects": subprojects_data,
            "Session History": history,
        }

    return projects_data


def json_compress(j):
    ZIPJSON_KEY = "base64(zip(o))"
    j = {
        ZIPJSON_KEY: base64.b64encode(
            zlib.compress(json.dumps(j).encode("utf-8"))
        ).decode("ascii")
    }

    return j


def json_decompress(content: dict | str | bytes) -> dict:
    ZIPJSON_KEY = "base64(zip(o))"

    # convert binary content to string
    if isinstance(content, bytes):
        content = content.decode("utf-8")

    if isinstance(content, str):
        try:
            content = json.loads(content)
        except Exception:
            raise RuntimeError("Could not interpret the contents")

    try:
        assert content[ZIPJSON_KEY]
        assert set(content.keys()) == {ZIPJSON_KEY}
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


def get_period_bounds(
    period: str, reference_date: datetime = None
) -> tuple[datetime, datetime]:
    """
    Calculate the start and end datetime for a given period.

    :param period: One of 'daily', 'weekly', 'fortnightly', 'monthly', 'quarterly', 'yearly'
    :param reference_date: The date to calculate bounds for (defaults to now)
    :return: Tuple of (start, end) as timezone-aware datetimes
    """
    if reference_date is None:
        reference_date = timezone.now()

    # Ensure we're working with timezone-aware datetime
    if timezone.is_naive(reference_date):
        reference_date = timezone.make_aware(reference_date)

    # Get the start of the day for reference
    ref_date = reference_date.date()

    if period == "daily":
        start_date = ref_date
        end_date = ref_date + timedelta(days=1)

    elif period == "weekly":
        # Week starts on Monday (weekday() returns 0 for Monday)
        days_since_monday = ref_date.weekday()
        start_date = ref_date - timedelta(days=days_since_monday)
        end_date = start_date + timedelta(days=7)

    elif period == "fortnightly":
        # Two-week period starting on Monday
        # Use ISO week number to determine which fortnight
        days_since_monday = ref_date.weekday()
        week_start = ref_date - timedelta(days=days_since_monday)
        iso_week = week_start.isocalendar()[1]
        # Odd weeks start a new fortnight
        if iso_week % 2 == 0:
            start_date = week_start - timedelta(days=7)
        else:
            start_date = week_start
        end_date = start_date + timedelta(days=14)

    elif period == "monthly":
        start_date = ref_date.replace(day=1)
        # Move to first day of next month
        end_date = start_date + relativedelta(months=1)

    elif period == "quarterly":
        # Q1: Jan-Mar, Q2: Apr-Jun, Q3: Jul-Sep, Q4: Oct-Dec
        quarter_month = ((ref_date.month - 1) // 3) * 3 + 1
        start_date = ref_date.replace(month=quarter_month, day=1)
        end_date = start_date + relativedelta(months=3)

    elif period == "yearly":
        start_date = ref_date.replace(month=1, day=1)
        end_date = start_date + relativedelta(years=1)

    else:
        raise ValueError(f"Unknown period: {period}")

    # Convert dates to timezone-aware datetimes at midnight
    start = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
    end = timezone.make_aware(datetime.combine(end_date, datetime.min.time()))

    return start, end


def get_commitment_progress(commitment) -> dict:
    """
    Calculate the progress for a commitment in the current period.

    :param commitment: A Commitment instance
    :return: Dict with actual, target, percentage, balance, status, period_start, period_end
    """
    from core.models import Sessions  # Import here to avoid circular import

    period_start, period_end = get_period_bounds(commitment.period)

    # Get completed sessions for this project in the current period
    sessions = Sessions.objects.filter(
        project=commitment.project,
        is_active=False,
        end_time__gte=period_start,
        end_time__lt=period_end,
    )

    if commitment.commitment_type == "time":
        # Sum durations in minutes
        total_duration = sum(s.duration or 0 for s in sessions)
        actual = round(total_duration, 2)
    else:
        # Count sessions
        actual = sessions.count()

    target = commitment.target
    percentage = min(round((actual / target) * 100, 1), 100) if target > 0 else 0

    # Determine status for progress bar styling
    if percentage >= 100:
        status = "complete"
    elif percentage >= 75:
        status = "approaching"
    elif percentage >= 50:
        status = "on-track"
    elif percentage >= 25:
        status = "warning"
    else:
        status = "behind"

    # Calculate surplus/deficit for this period (not yet banked)
    current_surplus = actual - target

    return {
        "actual": actual,
        "target": target,
        "percentage": percentage,
        "balance": commitment.balance,
        "current_surplus": round(current_surplus, 2),
        "status": status,
        "period_start": period_start,
        "period_end": period_end,
        "commitment_type": commitment.commitment_type,
        "period": commitment.period,
    }


def calculate_daily_activity_streak(user, reference_date=None) -> dict:
    """
    Calculate consecutive days with any logged time.

    :param user: User instance
    :param reference_date: The date to calculate from (defaults to now)
    :return: Dict with 'current_streak' (int) and 'recent_days' (list of 14 dicts with date and active status)
    """
    from core.models import Sessions  # Import here to avoid circular import

    if reference_date is None:
        reference_date = timezone.now()

    if timezone.is_naive(reference_date):
        reference_date = timezone.make_aware(reference_date)

    today = reference_date.date()

    # Get all completed session dates for this user
    sessions = Sessions.objects.filter(
        user=user, is_active=False, end_time__isnull=False
    ).values_list("end_time", flat=True)

    # Convert to set of dates (in local timezone)
    active_dates = set()
    for end_time in sessions:
        if end_time:
            local_date = timezone.localtime(end_time).date()
            active_dates.add(local_date)

    # Calculate current streak
    current_streak = 0
    check_date = today

    # If no activity today, start checking from yesterday
    if today not in active_dates:
        check_date = today - timedelta(days=1)

    # Count consecutive days
    while check_date in active_dates:
        current_streak += 1
        check_date -= timedelta(days=1)

    # Generate 14-day history for visual display
    recent_days = []
    for i in range(13, -1, -1):  # 14 days, oldest first
        day = today - timedelta(days=i)
        recent_days.append({"date": day, "active": day in active_dates})

    return {"current_streak": current_streak, "recent_days": recent_days}


def calculate_commitment_streak(commitment, num_periods=8) -> dict:
    """
    Calculate consecutive periods where commitment target was met.

    :param commitment: A Commitment instance
    :param num_periods: Number of periods to return for visual display
    :return: Dict with 'current_streak' (int) and 'periods' (list of period status dicts)
    """
    from core.models import Sessions  # Import here to avoid circular import

    now = timezone.now()
    periods = []
    current_streak = 0
    streak_broken = False

    # Work backwards through periods
    for i in range(num_periods):
        if i == 0:
            # Current period
            period_start, period_end = get_period_bounds(commitment.period, now)
            is_current = True
        else:
            # Previous periods
            # Go back by the period duration
            if commitment.period == "daily":
                ref_date = now - timedelta(days=i)
            elif commitment.period == "weekly":
                ref_date = now - timedelta(weeks=i)
            elif commitment.period == "fortnightly":
                ref_date = now - timedelta(weeks=i * 2)
            elif commitment.period == "monthly":
                ref_date = now - relativedelta(months=i)
            elif commitment.period == "quarterly":
                ref_date = now - relativedelta(months=i * 3)
            elif commitment.period == "yearly":
                ref_date = now - relativedelta(years=i)
            else:
                ref_date = now - timedelta(weeks=i)

            period_start, period_end = get_period_bounds(commitment.period, ref_date)
            is_current = False

        # Skip periods before commitment was created
        if commitment.created_at >= period_end:
            continue

        # Get sessions for this period
        sessions = Sessions.objects.filter(
            project=commitment.project,
            is_active=False,
            end_time__gte=period_start,
            end_time__lt=period_end,
        )

        if commitment.commitment_type == "time":
            actual = sum(s.duration or 0 for s in sessions)
        else:
            actual = sessions.count()

        target_met = actual >= commitment.target

        periods.append(
            {
                "period_start": period_start,
                "period_end": period_end,
                "actual": actual,
                "target": commitment.target,
                "met": target_met,
                "is_current": is_current,
            }
        )

        # Calculate streak (only count completed periods)
        if not is_current and not streak_broken:
            if target_met:
                current_streak += 1
            else:
                streak_broken = True

    # Reverse so oldest is first (for display)
    periods.reverse()

    return {"current_streak": current_streak, "periods": periods}


def reconcile_commitment(commitment, force: bool = False) -> bool:
    """
    Update the commitment balance when the period has ended.
    Called automatically when viewing a project page.

    :param commitment: A Commitment instance
    :param force: If True, reconcile even if already reconciled for this period
    :return: True if reconciliation occurred, False otherwise
    """
    from core.models import Sessions  # Import here to avoid circular import

    now = timezone.now()
    period_start, period_end = get_period_bounds(commitment.period)

    # Skip if commitment was created after this period started
    if commitment.created_at >= period_end:
        return False

    # Check if we've already reconciled for the previous period
    if commitment.last_reconciled:
        # Get the previous period's bounds
        prev_period_start, prev_period_end = get_period_bounds(
            commitment.period, period_start - timedelta(days=1)
        )

        # If we've already reconciled within the current period, skip
        if commitment.last_reconciled >= period_start and not force:
            return False

    # Only reconcile past periods, not the current one
    # We need to find all periods between last_reconciled and now that haven't been processed
    periods_to_reconcile = []

    if commitment.last_reconciled:
        check_date = commitment.last_reconciled
    else:
        # Start from when commitment was created
        check_date = commitment.created_at

    # Find all complete periods that need reconciliation
    while True:
        check_start, check_end = get_period_bounds(commitment.period, check_date)

        # If this period hasn't ended yet, stop
        if check_end > now:
            break

        # If commitment was created during this period, adjust the start
        effective_start = max(check_start, commitment.created_at)

        # Only add if we haven't reconciled this period yet
        if not commitment.last_reconciled or check_end > commitment.last_reconciled:
            periods_to_reconcile.append((effective_start, check_end))

        # Move to next period
        check_date = check_end + timedelta(seconds=1)

    if not periods_to_reconcile:
        return False

    # Process each period
    for p_start, p_end in periods_to_reconcile:
        sessions = Sessions.objects.filter(
            project=commitment.project,
            is_active=False,
            end_time__gte=p_start,
            end_time__lt=p_end,
        )

        if commitment.commitment_type == "time":
            actual = sum(s.duration or 0 for s in sessions)
        else:
            actual = sessions.count()

        surplus = actual - commitment.target

        if commitment.banking_enabled:
            # Update balance with clamping
            new_balance = commitment.balance + surplus
            new_balance = max(
                commitment.min_balance, min(commitment.max_balance, new_balance)
            )
            commitment.balance = int(new_balance)

    commitment.last_reconciled = now
    commitment.save()

    return True
