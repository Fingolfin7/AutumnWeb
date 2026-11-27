"""Timeline data for the Focus Desk dashboard.

Turns a user's sessions over a window of one or more days into project lanes
of blocks positioned on a time axis, plus the gaps between them and a "now"
marker.

Everything is expressed in **percentages of the visible window** so the
template can position blocks with plain CSS custom properties and the chart
reflows at any width without JS.

Two axis shapes, one engine:

* ``today``    one day, hour axis, window widened past 06:00-22:00 to fit
               anything that falls outside it.
* ``d3``/``wk`` three or seven whole days, day axis, each label centred over
               its own day rather than sitting on a boundary.

Timezone: all arithmetic happens in the *currently active* timezone.
``users.middleware`` activates the user's profile timezone for every request,
so inside a view ``timezone.localtime()`` is already user-local. Tests should
activate a timezone explicitly rather than passing one in.
"""

from datetime import UTC, datetime, time, timedelta

from django.utils import timezone

from core.models import Sessions

#: Hours the single-day axis always shows, even on an empty or tightly-packed
#: day. The window widens beyond this when sessions fall outside it.
DEFAULT_WINDOW_START = 6
DEFAULT_WINDOW_END = 22

#: Brief pauses between tasks do not need a timeline action.
MIN_GAP_MINUTES = 5

#: Selectable ranges, in days. The keys are what the range tabs send.
RANGE_DAYS = {"today": 1, "d3": 3, "wk": 7}
DEFAULT_RANGE = "today"

#: Lane colours. The semantic convention fixes "project = red", so lanes are
#: shades of red rather than an arbitrary categorical palette — hue-value
#: identifies the project without breaking the convention.
LANE_COLOURS = ["#d0796f", "#c2665e", "#a8564f", "#b8746a", "#94473f", "#cf8a76"]


def _aware(day, hour=0):
    return timezone.make_aware(datetime.combine(day, time(hour=hour)))


def _midnight_after(day):
    return _aware(day) + timedelta(days=1)


def _window_hours_for(spans, now_local, is_today):
    """Pick the single-day axis window (start_hour, end_hour).

    Starts from the default 06:00-22:00 and widens to fit any session — and
    the now-marker — that falls outside it, so nothing is ever drawn off the
    edge of the chart.
    """
    start_hour, end_hour = DEFAULT_WINDOW_START, DEFAULT_WINDOW_END

    for span_start, span_end in spans:
        start_hour = min(start_hour, span_start.hour)
        # a session ending at 22:30 needs the axis to reach 23
        ceiling = 24 if span_end.date() > span_start.date() else span_end.hour + bool(
            span_end.minute or span_end.second or span_end.microsecond
        )
        end_hour = max(end_hour, ceiling)

    if is_today:
        start_hour = min(start_hour, now_local.hour)
        end_hour = max(end_hour, now_local.hour + 1)

    return max(0, start_hour), min(24, max(end_hour, start_hour + 1))


def _pct(moment, window_start, window_minutes):
    """Position of ``moment`` as a percentage across the window."""
    offset = (moment.timestamp() - window_start.timestamp()) / 60.0
    return round(max(0.0, min(100.0, offset / window_minutes * 100.0)), 4)


def _compact_minutes(minutes):
    """Short duration label, e.g. "45m" or "1h 08m".

    Block and gap labels are drawn inside boxes a few dozen pixels wide, so
    they get their own tighter format than the app's general duration filters
    produce.
    """
    hours, mins = divmod(int(round(minutes)), 60)
    return f"{hours}h {mins:02d}m" if hours else f"{mins}m"


def _collect_gaps(spans, window_start, window_minutes):
    """Untracked stretches between the first and last activity of the day.

    Spans are merged first, so overlapping sessions on different projects
    don't manufacture a gap that wasn't there.
    """
    if not spans:
        return []

    merged = []
    # In the repeated hour at the end of DST, local times with the same
    # tzinfo compare by wall clock. Merge on absolute instants instead.
    for span_start, span_end in sorted((a.astimezone(UTC), b.astimezone(UTC)) for a, b in spans):
        if merged and span_start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], span_end)
        else:
            merged.append([span_start, span_end])

    gaps = []
    for (_, prev_end), (next_start, _) in zip(merged, merged[1:]):
        minutes = (next_start - prev_end).total_seconds() / 60.0
        if minutes < MIN_GAP_MINUTES:
            continue
        start_pct = _pct(prev_end, window_start, window_minutes)
        gaps.append({
            "start": prev_end.isoformat(),
            "end": next_start.isoformat(),
            "minutes": int(round(minutes)),
            "label": _compact_minutes(minutes),
            "start_pct": start_pct,
            "width_pct": round(_pct(next_start, window_start, window_minutes) - start_pct, 4),
        })
    return gaps


def _hour_ticks(start, end):
    """One label per hour boundary, positioned on the boundary itself.

    Every second label is flagged minor so a phone can thin them out — 17
    hour labels will not fit across 358px.
    """
    span = end.timestamp() - start.timestamp()
    ticks = []
    for index in range(int(span // 3600) + 1):
        local = datetime.fromtimestamp(start.timestamp() + index * 3600, start.tzinfo)
        ticks.append({
            "label": local.strftime("%H:%M" if local.minute else "%H"),
            "x_pct": round(index * 3600 / span * 100.0, 4),
            "minor": bool(index % 2),
        })
    return ticks


def _day_ticks(start_day, days):
    """One label per day, centred over that day's slice of the axis.

    Boundary-anchored labels read wrong on a multi-day axis: a label sitting
    on midnight belongs to neither of the days it separates.
    """
    width = 100.0 / days
    return [
        {
            "label": (start_day + timedelta(days=index)).strftime("%a %d"),
            "x_pct": round(width * (index + 0.5), 4),
            "minor": False,
        }
        for index in range(days)
    ]


def build_timeline(
    user,
    range_key=DEFAULT_RANGE,
    end_day=None,
    *,
    start_day=None,
    context=None,
):
    """Lanes, gaps and a now-marker for ``user`` over the selected range.

    Returns a dict shaped for direct template consumption. ``lanes`` is empty
    when the window has no activity; callers should render an empty state
    rather than an empty chart.
    """
    if start_day is None:
        if range_key not in RANGE_DAYS:
            range_key = DEFAULT_RANGE
        days = RANGE_DAYS[range_key]
    else:
        end_day = end_day or start_day
        if start_day > end_day:
            raise ValueError("start_day must be on or before end_day")
        days = (end_day - start_day).days + 1
        range_key = "custom"
    multi_day = days > 1

    end_day = end_day or timezone.localdate()
    start_day = start_day or end_day - timedelta(days=days - 1)
    now = timezone.now()
    now_local = timezone.localtime(now)
    today_in_range = start_day <= timezone.localdate() <= end_day

    range_start = _aware(start_day)
    range_end = _midnight_after(end_day)

    sessions = (
        Sessions.objects
        .filter(user=user, start_time__lt=range_end)
        .filter(_overlapping(range_start))
        .select_related("project")
        .prefetch_related("subprojects")
        .order_by("start_time")
    )
    if context is not None:
        sessions = sessions.filter(project__context=context)

    entries = []
    spans = []
    for session in sessions:
        running = session.end_time is None
        # A running timer is drawn up to now; a session crossing the window
        # edge is clipped to it, so widths always match the axis.
        raw_end = now if running else session.end_time
        block_start = timezone.localtime(max(session.start_time, range_start.astimezone(UTC)))
        block_end = timezone.localtime(min(raw_end, range_end.astimezone(UTC)))
        if block_end.timestamp() <= block_start.timestamp():
            continue
        entries.append((session, block_start, block_end, running))
        spans.append((block_start, block_end))

    if multi_day:
        window_start, window_end = range_start, range_end
        start_hour = end_hour = None
        ticks = _day_ticks(start_day, days)
        grid_pct = round(100.0 / days, 4)
        title = _range_title(start_day, end_day)
    else:
        start_hour, end_hour = _window_hours_for(spans, now_local, today_in_range)
        window_start = _aware(end_day, start_hour)
        window_end = _midnight_after(end_day) if end_hour >= 24 else _aware(end_day, end_hour)
        ticks = _hour_ticks(window_start, window_end)
        grid_pct = round(360000.0 / (window_end.timestamp() - window_start.timestamp()), 4)
        title = "{:02d}:00 – {:02d}:00".format(start_hour, end_hour % 24)

    window_minutes = (window_end.timestamp() - window_start.timestamp()) / 60.0

    lanes_by_project = {}
    for session, block_start, block_end, running in entries:
        minutes = (block_end.timestamp() - block_start.timestamp()) / 60.0
        start_pct = _pct(block_start, window_start, window_minutes)
        end_pct = _pct(block_end, window_start, window_minutes)
        lane = lanes_by_project.setdefault(session.project_id, {
            "project": session.project,
            "total_minutes": 0.0,
            "live_minutes": 0.0,
            "blocks": [],
        })
        lane["blocks"].append({
            "session": session,
            "is_live": running,
            "minutes": minutes,
            "duration_label": _compact_minutes(minutes),
            "start_pct": start_pct,
            # end_pct is not redundant with start+width: a live block is
            # anchored by its END so that a just-started timer, widened to the
            # minimum readable width, grows backwards instead of poking past
            # the now-marker into time that has not happened.
            "end_pct": end_pct,
            "width_pct": round(end_pct - start_pct, 4),
            "label": ", ".join(sub.name for sub in session.subprojects.all()),
            "start_local": block_start,
            "end_local": None if running else block_end,
        })
        if running:
            lane["live_minutes"] += minutes
        else:
            lane["total_minutes"] += minutes

    lanes = sorted(
        lanes_by_project.values(),
        key=lambda lane: lane["total_minutes"] + lane["live_minutes"],
        reverse=True,
    )
    for index, lane in enumerate(lanes):
        lane["colour"] = LANE_COLOURS[index % len(LANE_COLOURS)]
        # A lane head reads "3h 11m + 43m live". The completed figure is
        # omitted when a lane is nothing but a running timer, so a fresh timer
        # doesn't announce itself as "0m".
        lane["total_label"] = _compact_minutes(lane["total_minutes"]) if lane["total_minutes"] else None
        lane["live_label"] = _compact_minutes(lane["live_minutes"]) if lane["live_minutes"] else None

    now_pct = None
    if today_in_range and window_start <= now <= window_end:
        now_pct = _pct(now, window_start, window_minutes)

    tracked_minutes = sum(lane["total_minutes"] + lane["live_minutes"] for lane in lanes)

    if not multi_day and context is not None and len(spans) > 1:
        # Other contexts stay off the chart, but their recorded time is
        # occupied. Don't offer it as a gap to fill between visible sessions.
        first = min(start.astimezone(UTC) for start, _ in spans)
        last = max(end.astimezone(UTC) for _, end in spans)
        hidden = (
            Sessions.objects.filter(user=user, start_time__lt=last)
            .exclude(project__context=context).filter(_overlapping(first))
            .values_list("start_time", "end_time")
        )
        for start, end in hidden:
            start, end = max(first, start), min(last, end or now)
            if start < end:
                spans.append((start, end))

    return {
        "range_key": range_key,
        "range_title": title,
        "is_multi_day": multi_day,
        # Summed from the lanes rather than re-queried, so the headline figure
        # can never disagree with the chart under it.
        "tracked_minutes": tracked_minutes,
        "start_day": start_day,
        "date": end_day,
        # Hour bounds of the single-day axis, after any widening. None on the
        # multi-day views, whose axis is measured in days.
        "window_start_hour": start_hour,
        "window_end_hour": end_hour,
        "ticks": ticks,
        "grid_pct": grid_pct,
        "lanes": lanes,
        # Overnight "gaps" on a multi-day axis are just nights; labelling them
        # as untracked time would be noise, not information.
        "gaps": [] if multi_day else _collect_gaps(spans, window_start, window_minutes),
        "now_pct": now_pct,
        "now_label": timezone.localtime(now).strftime("%H:%M") if now_pct is not None else None,
        # The client ticks live blocks forward between polls; it needs the
        # window in absolute terms to do that without asking the server.
        "window_start_iso": window_start.isoformat(),
        "window_end_iso": window_end.isoformat(),
    }


def build_day_timeline(user, day=None):
    """Single-day timeline. Thin wrapper kept for callers and tests."""
    return build_timeline(user, DEFAULT_RANGE, end_day=day)


def _range_title(start_day, end_day):
    """e.g. "Mon 20 – Sun 26 Jul", collapsing a repeated month."""
    if start_day.month == end_day.month:
        return f"{start_day.strftime('%a %d')} – {end_day.strftime('%a %d %b')}"
    return f"{start_day.strftime('%a %d %b')} – {end_day.strftime('%a %d %b')}"


def _overlapping(range_start):
    """Sessions that are unfinished, or that ended on/after ``range_start``.

    Split out so the filter reads clearly at the call site: a session belongs
    to the window if it overlaps it, not merely if it started in it.
    """
    from django.db.models import Q

    return Q(end_time__isnull=True) | Q(end_time__gt=range_start)
